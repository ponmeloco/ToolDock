FROM python:3.12-slim
WORKDIR /app
COPY core/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core/ .
EXPOSE 8000
CMD ["python", "main.py"]
