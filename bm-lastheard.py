# SPDX-License-Identifier: GPL-3.0-only
import socketio
import requests
import re
from datetime import datetime, timezone
import argparse
import sys
import time
import json
import threading
import select
import csv
import os
from pathlib import Path

BM_PEER_URL = "https://api.brandmeister.network/v2/device/"
RADIOID_CSV_URL = "https://radioid.net/static/user.csv"
CACHE_DIR = Path.home() / ".cache" / "bm-lastheard"
CSV_FILE = CACHE_DIR / "user.csv"
CSV_MAX_AGE = 14 * 24 * 60 * 60  # 2 weeks in seconds

# In-memory maps for fast DMR ID lookups
dmr_callsign_map = {}
dmr_firstname_map = {}
dmr_city_map = {}
dmr_country_map = {}

def ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

def is_csv_stale():
    if not CSV_FILE.exists():
        return True
    file_age = time.time() - CSV_FILE.stat().st_mtime
    return file_age > CSV_MAX_AGE

def download_csv():
    print("Downloading RadioID user database...", file=sys.stderr)
    try:
        r = requests.get(RADIOID_CSV_URL, timeout=30)
        if r.status_code == 200:
            ensure_cache_dir()
            CSV_FILE.write_text(r.text)
            print("Database downloaded successfully.", file=sys.stderr)
            return True
    except Exception as e:
        print(f"Failed to download database: {e}", file=sys.stderr)
    return False

def load_dmr_database():
    global dmr_callsign_map, dmr_firstname_map, dmr_city_map, dmr_country_map

    if is_csv_stale():
        if not download_csv():
            if not CSV_FILE.exists():
                print("Warning: No user database available. Callsign lookups will be unavailable.", file=sys.stderr)
                return

    print("Loading RadioID database...", file=sys.stderr)
    try:
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                dmr_id = row.get('RADIO_ID', '').strip()
                callsign = row.get('CALLSIGN', '').strip()
                firstname = row.get('FIRST_NAME', '').strip()
                city = row.get('CITY', '').strip()
                country = row.get('COUNTRY', '').strip()
                if dmr_id and callsign:
                    dmr_callsign_map[dmr_id] = callsign
                    dmr_firstname_map[dmr_id] = firstname
                    dmr_city_map[dmr_id] = city
                    dmr_country_map[dmr_id] = country
        print(f"Loaded {len(dmr_callsign_map)} callsigns.", file=sys.stderr)
    except Exception as e:
        print(f"Failed to load database: {e}", file=sys.stderr)

def get_peer_info(peer_id):
    try:
        r = requests.get(f"{BM_PEER_URL}{peer_id}", timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except:
        return None

def get_user_callsign(dmr_id):
    return dmr_callsign_map.get(dmr_id, None)

def get_user_firstname(dmr_id):
    return dmr_firstname_map.get(dmr_id, "")

def get_user_city(dmr_id):
    return dmr_city_map.get(dmr_id, "")

def get_user_country(dmr_id):
    return dmr_country_map.get(dmr_id, "")

def format_timestamp(ts):
    dt = datetime.fromtimestamp(ts, timezone.utc)
    return dt.strftime("%H:%M:%S")

def main(callsign_filter=None, dest_filter=None, peer_filter=None, show_name=False, enable_logging=False, runtime_minutes=None):
    # Load DMR database first
    load_dmr_database()

    # Calculate end time if runtime is specified
    end_time = None
    if runtime_minutes:
        end_time = time.time() + (runtime_minutes * 60)
        print(f"Will run for {runtime_minutes} minute(s)", file=sys.stderr)

    # Create log file if logging is enabled
    # Use a dict to allow modification in nested functions
    log_state = {'file': None, 'filename': None}
    if enable_logging:
        # Create logs directory if it doesn't exist
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # Create log file with timestamp
        start_time = datetime.now(timezone.utc)
        log_state['filename'] = log_dir / start_time.strftime("%Y%m%d%H%M%S_bm-lastheard.txt")
        log_state['file'] = open(log_state['filename'], 'w', encoding='utf-8')
        print(f"Logging to: {log_state['filename']}", file=sys.stderr)

    callsign_pattern = re.compile(callsign_filter, re.IGNORECASE) if callsign_filter else None

    # Track recent sessions to avoid duplicates
    seen_sessions = {}  # session_id -> timestamp

    # Setup for real-time monitoring with keyboard control
    filters_active = []
    if callsign_filter:
        filters_active.append(f"Callsign: {callsign_filter}")
    if dest_filter:
        filters_active.append(f"TG: {dest_filter}")
    if peer_filter:
        filters_active.append(f"Peer: {peer_filter}")

    if filters_active:
        print(f"Filters: {', '.join(filters_active)}", file=sys.stderr)
    print("Press 'q' or ESC to quit (Ctrl+C also works)...\n", file=sys.stderr)

    stop_flag = threading.Event()
    sio = None

    def keyboard_listener():
        # Only enable keyboard control if stdin is a TTY
        if not sys.stdin.isatty():
            return

        import termios
        import tty

        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())
            while not stop_flag.is_set():
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    char = sys.stdin.read(1)
                    if char in ('q', 'Q', '\x1b'):  # q, Q, or ESC
                        stop_flag.set()
                        if sio:
                            sio.disconnect()
                        break
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    # Start keyboard listener thread
    kb_thread = threading.Thread(target=keyboard_listener, daemon=True)
    kb_thread.start()

    # Connect to WebSocket
    try:
        sio = socketio.Client()
    except Exception as e:
        print(f"Error initializing socketio client: {e}", file=sys.stderr)
        sys.exit(1)

    @sio.event
    def connect():
        print("Connected to BrandMeister...", file=sys.stderr)
        if show_name:
            header = "UTC      | DMR ID   | Callsign | Repeater/Node     | Talkgroup | Country            | City              | Name"
            separator = "-" * 121
        else:
            header = "UTC      | DMR ID   | Callsign | Repeater/Node     | Talkgroup | Country            | City"
            separator = "-" * 96

        print(f"\n{header}", file=sys.stderr)
        print(separator, file=sys.stderr)

        # Write header to log file if logging is enabled
        if log_state['file'] and not log_state['file'].closed:
            print(header, file=log_state['file'])
            print(separator, file=log_state['file'])
            log_state['file'].flush()

    @sio.on('mqtt')
    def on_mqtt(data):
        if stop_flag.is_set():
            return

        if 'payload' in data and isinstance(data['payload'], str):
            try:
                entry = json.loads(data['payload'])

                # Only process Session-Stop events
                # Reason: Session-Start and Session-Progress events don't contain the actual
                # repeater callsign in LinkCall field. Only Session-Stop events have complete
                # repeater information.
                event_type = entry.get("Event", "")
                if event_type != "Session-Stop":
                    return

                # Track session ID to deduplicate
                session_id = entry.get("SessionID", "")
                current_time = time.time()

                # Skip if we've seen this session in the last 30 seconds
                if session_id in seen_sessions:
                    if current_time - seen_sessions[session_id] < 30:
                        return

                # Record this session
                seen_sessions[session_id] = current_time

                # Clean up old sessions (older than 60 seconds)
                old_sessions = [sid for sid, ts in seen_sessions.items() if current_time - ts > 60]
                for sid in old_sessions:
                    del seen_sessions[sid]

                # New WebSocket format uses different field names
                callsign = entry.get("SourceCall", "").strip()
                dmr_id = str(entry.get("SourceID", ""))
                peer = str(entry.get("Master", ""))
                destination = str(entry.get("DestinationID", ""))
                timestamp = entry.get("Start", 0)
                link_call = entry.get("LinkCall", "").strip()
                link_type = entry.get("LinkTypeName", "").strip()
                link_name = entry.get("LinkName", "").strip()

                # If callsign is empty, look it up from the local database
                if not callsign and dmr_id and dmr_id != "0":
                    user_callsign = get_user_callsign(dmr_id)
                    if user_callsign:
                        callsign = user_callsign

                # Skip old data (more than 2 minutes old)
                if timestamp > 0 and (current_time - timestamp) > 120:
                    return

                # Apply filters
                if callsign_pattern:
                    if not (callsign_pattern.search(callsign) or callsign_pattern.search(link_call)):
                        return

                if dest_filter and destination != dest_filter:
                    return

                if peer_filter and peer != peer_filter:
                    return

                # Get repeater/hotspot info
                # Priority: LinkCall (if different and not empty), then LinkName (if meaningful), then HOTSPOT/REPEATER
                if link_call and link_call != callsign:
                    # LinkCall has the repeater callsign - crop smartly at word boundary
                    if len(link_call) <= 17:
                        repeater_cs = link_call
                    else:
                        # Find last space before position 17
                        truncated = link_call[:17]
                        last_space = truncated.rfind(' ')
                        if last_space > 0:
                            repeater_cs = link_call[:last_space]
                        else:
                            repeater_cs = link_call[:17]
                elif link_type == "Repeater" and link_name and link_name not in ["MMDVM Host", "Homebrew Repeater"]:
                    # It's a repeater but LinkCall is missing - show generic REPEATER marker
                    repeater_cs = "REPEATER"
                else:
                    # User's own hotspot/repeater or no link info
                    repeater_cs = "HOTSPOT"

                # Get country and city from database (always)
                country = get_user_country(dmr_id) if dmr_id else ""
                city = get_user_city(dmr_id) if dmr_id else ""

                # Crop country to 18 chars - find last complete word + first char of next word + dot
                if len(country) <= 18:
                    country_display = country
                else:
                    truncated = country[:17]
                    last_space = truncated.rfind(' ')
                    if last_space > 0 and last_space < len(country) - 1:
                        # Show up to last space + first char of next word + dot
                        country_display = country[:last_space + 2] + "."
                    else:
                        country_display = country[:17] + "."

                # Crop city to 17 chars - find last complete word + first char of next word + dot
                if len(city) <= 17:
                    city_display = city
                else:
                    truncated = city[:16]
                    last_space = truncated.rfind(' ')
                    if last_space > 0 and last_space < len(city) - 1:
                        # Show up to last space + first char of next word + dot
                        city_display = city[:last_space + 2] + "."
                    else:
                        city_display = city[:16] + "."

                # Format output
                if show_name:
                    firstname = get_user_firstname(dmr_id) if dmr_id else ""
                    line = f"{format_timestamp(timestamp)} | {dmr_id:<8} | {callsign:<8} | {repeater_cs:<17} | {destination:<9} | {country_display:<18} | {city_display:<17} | {firstname}"
                else:
                    line = f"{format_timestamp(timestamp)} | {dmr_id:<8} | {callsign:<8} | {repeater_cs:<17} | {destination:<9} | {country_display:<18} | {city_display}"

                print(line)
                sys.stdout.flush()

                # Write to log file if logging is enabled
                if log_state['file'] and not log_state['file'].closed:
                    print(line, file=log_state['file'])
                    log_state['file'].flush()
            except json.JSONDecodeError:
                pass

    try:
        sio.connect('https://api.brandmeister.network', socketio_path='/lh/socket.io', transports=['websocket'])

        # Keep running until stop_flag is set or time expires
        while not stop_flag.is_set() and sio.connected:
            # Check if runtime has expired
            if end_time and time.time() >= end_time:
                print("\nRuntime expired, shutting down...", file=sys.stderr)
                stop_flag.set()
                break
            time.sleep(0.1)

        sio.disconnect()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
    finally:
        stop_flag.set()
        kb_thread.join(timeout=1)
        if log_state['file'] and not log_state['file'].closed:
            log_state['file'].close()
            print(f"\nLog file closed: {log_state['filename']}", file=sys.stderr)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="BrandMeister Last Heard Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                           # Monitor all worldwide activity
  %(prog)s -c OH                     # Filter by callsign prefix (OH for Finland)
  %(prog)s -t 91                     # Monitor TG 91 (Worldwide)
  %(prog)s -t 244                    # Monitor TG 244 (Finland National)
  %(prog)s -p 2441                   # Monitor BrandMeister master 2441 (Finland)
  %(prog)s -c OH -t 244              # Finnish stations on TG 244
  %(prog)s -p 2441 -t 91             # TG 91 activity through Finnish master
  %(prog)s -n                        # Show first names in output
  %(prog)s -l                        # Enable logging to logs/ folder
  %(prog)s -l -r 60                  # Log for 60 minutes then exit
  %(prog)s -t 244 -n -l -r 30        # Finnish TG with names, log 30 minutes

Filters:
  -c/--callsign  : Match callsigns using regex (e.g., OH, OH6, ^OH2)
  -t/--talkgroup : Filter by talkgroup number (e.g., 91, 244, 3100)
  -p/--peer      : Filter by BrandMeister master server ID (e.g., 2441 for Finland)

Display Options:
  -n/--name      : Add first name column to output
  -l/--log       : Write timestamped log file to logs/ directory
  -r/--runtime   : Run for specified minutes then exit (useful with -l)

Common Talkgroups:
  91      Worldwide
  244     Finland National
  2441    Finland Local
  3100    USA Nationwide

Common Master Servers:
  2441    Finland
  2222    Germany
  310XX   Various USA servers
        """
    )
    parser.add_argument(
        "-c", "--callsign",
        default=None,
        help="Filter by callsign (regex pattern, e.g., OH, OH6, ^OH2)"
    )
    parser.add_argument(
        "-t", "--talkgroup",
        default=None,
        help="Filter by talkgroup number (e.g., 91, 244, 3100)"
    )
    parser.add_argument(
        "-p", "--peer",
        default=None,
        help="Filter by BrandMeister master server ID (e.g., 2441 for Finland)"
    )
    parser.add_argument(
        "-n", "--name",
        action="store_true",
        help="Show first names in output"
    )
    parser.add_argument(
        "-l", "--log",
        action="store_true",
        help="Enable logging to logs/ directory"
    )
    parser.add_argument(
        "-r", "--runtime",
        type=int,
        default=None,
        help="Run for specified minutes then exit automatically"
    )
    args = parser.parse_args()
    main(callsign_filter=args.callsign, dest_filter=args.talkgroup, peer_filter=args.peer, show_name=args.name, enable_logging=args.log, runtime_minutes=args.runtime)

