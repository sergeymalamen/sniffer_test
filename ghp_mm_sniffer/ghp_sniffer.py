#!/usr/bin/env python3
# ghp_sniffer.py — adapted and extended
import sys
import serial
import paho.mqtt.client as mqtt
import struct
import json
import time
import logging
from pathlib import Path

# logging
logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("ghp_sniffer")

# load options from Home Assistant add-on options.json
OPTIONS_PATH = "/data/options.json"
if Path(OPTIONS_PATH).exists():
    with open(OPTIONS_PATH, "r") as f:
        options = json.load(f)
else:
    # fallback defaults
    options = {
        "serial_port": "/dev/ttyUSB0",
        "mqtt_broker": "homeassistant",
        "mqtt_port": 1883,
        "mqtt_username": "",
        "mqtt_password": "",
        "mqtt_prefix": "ghp08",
        "autodetect": False,
        "mapping": {}
    }

SERIAL_PORT = options.get("serial_port", "/dev/ttyUSB0")
MQTT_BROKER = options.get("mqtt_broker", "homeassistant")
MQTT_PORT = options.get("mqtt_port", 1883)
MQTT_USERNAME = options.get("mqtt_username", "")
MQTT_PASSWORD = options.get("mqtt_password", "")
MQTT_PREFIX = options.get("mqtt_prefix", "ghp08")
AUTODETECT = options.get("autodetect", False)
MAPPING = options.get("mapping", {})  # expected dict

# Helper topic builders
def raw_topic(op, slave, addr):
    return f"{MQTT_PREFIX}/{op}/{slave}/{addr}"

def state_topic(name):
    return f"{MQTT_PREFIX}/state/{name}"

def discovery_topic(domain, node_id):
    return f"homeassistant/{domain}/{node_id}/config"

# CRC functions (same as original)
def modbus_crc16(data: bytes) -> int:
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if (crc & 0x0001) != 0:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc

def verify_modbus_crc(data: bytes) -> bool:
    if len(data) < 4:
        return False
    received_crc = struct.unpack('<H', data[-2:])[0]
    calculated_crc = modbus_crc16(data[:-2])
    return received_crc == calculated_crc

# MQTT client setup
mqtt_client = mqtt.Client()
if MQTT_USERNAME:
    mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

def on_connect(client, userdata, flags, rc):
    _logger.info("MQTT connected, subscribing to set topic")
    client.subscribe(f"{MQTT_PREFIX}/set/#")

def on_message(client, userdata, msg):
    global writemsg
    _logger.info(f"MQTT received msg.topic={msg.topic} msg.payload={msg.payload}")
    addr_parts = msg.topic.split('/')
    # expected: prefix/set/<slave>/<addr>
    try:
        if len(addr_parts) >= 4 and addr_parts[1] == "set":
            slave = int(addr_parts[2])
            addr = int(addr_parts[3])
            payload = msg.payload.decode()
            # allow only safe write range same as original author (2000-2006)
            if 2000 <= addr <= 2006:
                newm = struct.pack(">BBhh", slave, 6, addr, int(payload))
                writemsg = newm
            else:
                _logger.error(f"Write request outside safe range (2000-2006): {addr}")
    except Exception as e:
        _logger.error(f"Error processing set message: {e}")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
mqtt_client.loop_start()
time.sleep(0.5)

# publishing helper — publishes raw register arrays and also mapped semantic sensors
def publish_raw_and_mapped(slave, op, addr, data_tuple):
    # data_tuple is a tuple of signed 16-bit integers
    try:
        payload = json.dumps(data_tuple)
    except Exception:
        payload = str(data_tuple)
    mt = raw_topic(op, slave, addr)
    mqtt_client.publish(mt, payload, retain=False)
    _logger.debug(f"Published raw {mt}: {payload}")

    # autodetect: publish candidate words for mapping inspection
    if AUTODETECT:
        # build candidates list: offset -> (be16, le16)
        candidates = []
        # we'll publish only first N words to reduce spam
        N = min(100, len(data_tuple))
        for i in range(N):
            val = data_tuple[i]
            candidates.append({"idx": i, "val": int(val)})
        meta = {"timestamp": int(time.time()), "slave": slave, "addr": addr, "candidates": candidates}
        mqtt_client.publish(f"{MQTT_PREFIX}/map/packet", json.dumps(meta), retain=False)

    # mapping: if user provided mapping entries, map them to semantic topics
    # expected MAPPING format:
    # { "<addr>": { "<offset>": {"name":"supply_temp","scale":0.1,"unit":"°C","device_class":"temperature"} } }
    try:
        addr_str = str(addr)
        if addr_str in MAPPING:
            for off_str, meta in MAPPING[addr_str].items():
                try:
                    off = int(off_str)
                    if off < len(data_tuple):
                        raw_value = data_tuple[off]
                        scale = float(meta.get("scale", 1.0))
                        value = raw_value * scale
                        name = meta.get("name", f"reg_{addr}_{off}")
                        # type conversions
                        if isinstance(value, float) and value.is_integer():
                            value = int(value)
                        mqtt_client.publish(state_topic(name), json.dumps(value), retain=meta.get("retain", False))
                        _logger.info(f"Published mapped {name} = {value}")
                        # Home Assistant discovery (publish once at startup for each mapped sensor)
                except Exception as e:
                    _logger.error(f"Mapping publish error for addr {addr} off {off_str}: {e}")
    except Exception as e:
        _logger.error(f"Mapping handling error: {e}")

# Discovery publisher (publish HA discovery for mapped items)
def publish_discovery():
    # for each mapping entry create HA discovery
    node = "ghp08"
    for addr_str, offs in MAPPING.items():
        for off_str, meta in offs.items():
            name = meta.get("name")
            if not name:
                continue
            domain = meta.get("domain", "sensor")
            node_id = f"{node}_{name}"
            dev = {
                "name": meta.get("title", name),
                "state_topic": state_topic(name),
                "unique_id": node_id,
                "device": {
                    "identifiers": [node],
                    "manufacturer": "Grundig/GHP",
                    "name": "GHP-MM"
                }
            }
            if meta.get("device_class"):
                dev["device_class"] = meta["device_class"]
            if meta.get("unit"):
                dev["unit_of_measurement"] = meta["unit"]
            # publish discovery
            try:
                mqtt_client.publish(discovery_topic(domain, node_id), json.dumps(dev), retain=True)
                _logger.info(f"Published discovery for {node_id}")
            except Exception as e:
                _logger.error(f"Error publishing discovery for {node_id}: {e}")

# decode logic adapted from original script
buffer = bytearray(0)
readAddr = 0
writemsg = b''

def decodeModbus():
    global buffer, readAddr, writemsg
    buflen = len(buffer)
    if buflen < 8:
        return
    index = buffer.find(240)  # find slave 0xF0
    if index < 0 or buflen - index < 8:
        # no start
        return
    buffer = buffer[index:]
    if buffer[1] == 3:  # read command / response
        # could be read request or response
        # request fixed size 8 (id + 03 + addr(2) + qty(2) + crc(2))
        if buflen >= 8 and verify_modbus_crc(buffer[0:8]):
            # this is probably a request
            readAddr = struct.unpack('>h', buffer[2:4])[0]
            buffer = buffer[8:]
        else:
            # response: size at buffer[2] + 5
            if len(buffer) < 3:
                return
            psize = buffer[2] + 5
            if len(buffer) >= psize and verify_modbus_crc(buffer[0:psize]):
                numshorts = int((psize - 5) / 2)
                data_tuple = struct.unpack(f'>{numshorts}h', buffer[3:psize-2])
                publish_raw_and_mapped(buffer[0], 3, readAddr, data_tuple)
                if len(writemsg) > 5:
                    # append crc and write
                    writemsg = writemsg + modbus_crc16(writemsg).to_bytes(2, 'little')
                    _logger.info(f"WRITE {writemsg}")
                    ser.write(writemsg)
                    writemsg = b''
                buffer = buffer[psize:]
            else:
                buffer = buffer[1:]
    elif buffer[1] == 16: # write command/response
        # size at buffer[6] + 9
        if len(buffer) < 7:
            return
        psize = buffer[6] + 9
        if len(buffer) >= psize and verify_modbus_crc(buffer[0:psize]):
            readAddr = struct.unpack('>h', buffer[2:4])[0]
            numshorts = int((psize - 9) / 2)
            data_tuple = struct.unpack(f'>{numshorts}h', buffer[7:psize-2])
            publish_raw_and_mapped(buffer[0], 10, readAddr, data_tuple)
            buffer = buffer[psize:]
        else:
            buffer = buffer[1:]
    else:
        buffer = buffer[1:]
    # recursive call attempt to parse remaining packets
    if len(buffer) >= 8:
        decodeModbus()

# open serial
try:
    ser = serial.Serial(
        port=SERIAL_PORT,
        baudrate=9600,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0
    )
    _logger.info(f"Serial port {SERIAL_PORT} opened")
    ser.reset_input_buffer()
except Exception as e:
    _logger.error(f"Cannot open serial port {SERIAL_PORT}: {e}")
    sys.exit(1)

# publish discovery for mapped items
publish_discovery()

try:
    _logger.info("Starting main loop")
    while True:
        # read incoming bytes
        try:
            data = ser.read(1)
            data += ser.read(ser.in_waiting or 0)
            if data:
                buffer += data
                decodeModbus()
            else:
                # nothing
                pass
        except Exception as e:
            _logger.error(f"Serial read error: {e}")
        time.sleep(0.05)
except KeyboardInterrupt:
    _logger.info("Keyboard interrupt")
finally:
    try:
        ser.close()
    except:
        pass
    mqtt_client.disconnect()
    _logger.info("Stopped")
