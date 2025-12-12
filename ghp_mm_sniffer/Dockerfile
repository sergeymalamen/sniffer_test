ARG BUILD_FROM=ghcr.io/home-assistant/{arch}-base:latest
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-pip

WORKDIR /usr/src/app

COPY requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

COPY ghp_sniffer.py .
COPY run.sh .

RUN chmod a+x /usr/src/app/run.sh

CMD [ "/usr/src/app/run.sh" ]
