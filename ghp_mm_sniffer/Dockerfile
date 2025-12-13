ARG BUILD_FROM=ghcr.io/home-assistant/{arch}-base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip

WORKDIR /usr/src/app

COPY requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

COPY ghp_sniffer.py .
COPY ghp_config_template.py .

# s6 service
COPY rootfs /

RUN chmod +x /usr/src/app/ghp_sniffer.py
