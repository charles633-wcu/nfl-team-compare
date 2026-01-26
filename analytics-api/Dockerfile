FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY analytics-api/ /app/

EXPOSE 8001
CMD ["uvicorn", "analytics_api:app", "--host", "0.0.0.0", "--port", "8001"]
