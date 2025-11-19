
import yaml

def load_registers(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("registers", [])
