FROM python:3.11-slim

WORKDIR /app

# Copy root requirements.txt into the image and install
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Copy the service code into /app (container)
COPY data-api/ /app/

EXPOSE 8000
CMD ["uvicorn", "data_api:app", "--host", "0.0.0.0", "--port", "8000"]
