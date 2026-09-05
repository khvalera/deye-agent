import yaml


def load_registers(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    registers = data.get("registers", [])

    if not isinstance(registers, list):
        raise ValueError(
            "registers must be a list in {}".format(filepath)
        )

    return registers
