FROM python:3.14

COPY requirements.txt bm-lastheard.py /app/

RUN pip install -r /app/requirements.txt

ENTRYPOINT ["python", "/app/bm-lastheard.py"]
