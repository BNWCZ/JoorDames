FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# src/ is on the path so modules import each other without package prefix
ENV PYTHONPATH=/app/src

CMD ["python", "src/main.py", "book"]
