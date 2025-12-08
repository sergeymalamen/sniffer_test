import json

CONFIG_PATH = "/data/options.json"

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)
