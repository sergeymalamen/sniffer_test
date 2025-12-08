ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest
FROM ${BUILD_FROM}

# Install Python
RUN apk add --no-cache python3 py3-pip

WORKDIR /usr/src/app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY ghp_mm2mqtt.py .
COPY ghp_config.py .
COPY run.sh .

RUN chmod a+x /usr/src/app/run.sh

CMD [ "/usr/src/app/run.sh" ]
