import os

CONFIG_PATH = "/etc/deye-agent/deye-agent.conf"
REGISTERS_FILE = "/etc/deye-agent/registers.yaml"
PROFILES_DIR = "/etc/deye-agent/profiles"
DEFAULT_PROFILE = "single_phase_storage"


def str_to_bool(s):
    return str(s).lower() in ("true", "1", "yes", "on")


def load_config(path=CONFIG_PATH):
    config = {}
    if not os.path.isfile(path):
        raise FileNotFoundError("Config file {} not found".format(path))

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                config[key.strip()] = val.strip().strip('"').strip("'")

    return config
