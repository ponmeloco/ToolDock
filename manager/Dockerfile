FROM python:3.12-slim
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY manager/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY manager/ .
EXPOSE 8001
CMD ["python", "main.py"]
