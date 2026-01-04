# BrandMeister Last Heard Monitor

## Usage:

`bm-lastheard.py [-h] [-c CALLSIGN] [-t TALKGROUP] [-p PEER] [-n] [-l] [-r RUNTIME]`

## Options:
```
-h, --help            show help message and exit
-c CALLSIGN, --callsign CALLSIGN
                      Filter by callsign (regex pattern, e.g., OH, OH6, ^OH2)
-t TALKGROUP, --talkgroup TALKGROUP
                      Filter by talkgroup number (e.g., 91, 244, 3100)
-p PEER, --peer PEER  Filter by BrandMeister master server ID (e.g., 2441 for Finland)
-n, --name            Show first names in output
-l, --log             Enable logging to logs/ directory
-r RUNTIME, --runtime RUNTIME
                      Run for specified minutes then exit automatically
```
## Examples:
```
bm-lastheard.py                           # Monitor all worldwide activity
bm-lastheard.py -c OH                     # Filter by callsign prefix (OH for Finland)
bm-lastheard.py -t 91                     # Monitor TG 91 (Worldwide)
bm-lastheard.py -t 244                    # Monitor TG 244 (Finland National)
bm-lastheard.py -p 2441                   # Monitor BrandMeister master 2441 (Finland)
bm-lastheard.py -c OH -t 244              # Finnish stations on TG 244
bm-lastheard.py -p 2441 -t 91             # TG 91 activity through Finnish master
bm-lastheard.py -n                        # Show first names in output
bm-lastheard.py -l                        # Enable logging to logs/ folder
bm-lastheard.py -l -r 60                  # Log for 60 minutes then exit
bm-lastheard.py -t 244 -n -l -r 30        # Finnish TG with names, log 30 minutes
```

## Filters:
```
-c/--callsign  : Match callsigns using regex (e.g., OH, OH6, ^OH2)
-t/--talkgroup : Filter by talkgroup number (e.g., 91, 244, 3100)
-p/--peer      : Filter by BrandMeister master server ID (e.g., 2441 for Finland)
```

## Display Options:
```
-n/--name      : Add first name column to output
-l/--log       : Write timestamped log file to logs/ directory
-r/--runtime   : Run for specified minutes then exit (useful with -l)
```

## Common Talkgroups:
```
91      Worldwide
244     Finland National
2441    Finland Local
3100    USA Nationwide
```

## Common Master Servers:
```
2441    Finland
2222    Germany
310XX   Various USA servers
```

## License
bm-lastheard - BrandMeister Last Heard Monitor.
Copyright (C) 2026 Tommi Tauriainen, OH8DMM.

This program is free software; you can redistribute it and/or modify it
under the terms of the GNU General Public License version 3 as published
by the Free Software Foundation.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
Public License for more details.

You should have received a copy of the GNU General Public License along
with this program. If not, see <https://www.gnu.org/licenses/>.
