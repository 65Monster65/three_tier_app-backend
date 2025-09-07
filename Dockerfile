#stage 1
FROM python:3.9-slim

# Install system packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        dnsutils \
    && rm -rf /var/lib/apt/lists/*

RUN update-ca-certificates --fresh

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
