FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

RUN pip install --no-cache-dir playwright==1.47.0

COPY watcher.py .

CMD ["python3", "watcher.py"]
