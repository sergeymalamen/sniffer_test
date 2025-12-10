import time
import serial
import paho.mqtt.client as mqtt
from ghp_config import load_config

cfg = load_config()

SERIAL_PORT = cfg["serial_port"]
MQTT_HOST   = cfg["mqtt_host"]
MQTT_PORT   = cfg["mqtt_port"]
TOPIC       = cfg["mqtt_topic"]

def connect_mqtt():
    client = mqtt.Client()
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    return client

def open_serial():
    return serial.Serial(
        SERIAL_PORT,
        baudrate=9600,
        timeout=1
    )

def main():
    mqtt_client = connect_mqtt()
    ser = open_serial()

    print("GHP-MM sniffer started")

    while True:
        line = ser.readline()
        if not line:
            continue

        decoded = line.hex(" ")
        mqtt_client.publish(TOPIC, decoded)
        print(">>", decoded)

        time.sleep(0.01)

if __name__ == "__main__":
    main()
