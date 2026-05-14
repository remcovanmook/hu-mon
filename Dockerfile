FROM python:3.13-slim

WORKDIR /opt/growatt

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default ports: dashboard (8081), Modbus proxy (5020)
EXPOSE 8081 5020

CMD ["python", "growatt_server.py"]
