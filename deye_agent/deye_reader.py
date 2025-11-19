
import time

#=================================
# CRC16 Modbus
#=================================
def calc_crc(data: bytes) -> bytes:
    import struct

    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return struct.pack('<H', crc)

#=================================
# Modbus request
#=================================
def build_request(slave_id, reg_addr: int, count: int = 1) -> bytes:
    frame = bytearray([
        slave_id,
        0x03,
        (reg_addr >> 8) & 0xFF,
        reg_addr & 0xFF,
        (count >> 8) & 0xFF,
        count & 0xFF
    ])
    frame.extend(calc_crc(frame))
    return bytes(frame)

#=================================
# Reading the register
#=================================
def read_register(ser, slave_id, reg_addr, count=1):
    try:
        req = build_request(slave_id, reg_addr, count)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        ser.write(req)
        time.sleep(0.2)
        resp = ser.read(5 + 2*count)
        if len(resp) < 5 + 2*count:
            return None
        if calc_crc(resp[:-2]) != resp[-2:]:
            return None
        byte_count = resp[2]
        values = []
        for i in range(byte_count // 2):
            hi = resp[3 + 2*i]
            lo = resp[3 + 2*i + 1]
            values.append((hi << 8) | lo)
        return values
    except Exception:
        return None

#=================================
# Read deye data function
#=================================
def read_deye_data(config, str_to_bool, registers_file):
    import serial
    import yaml

    PORT = config.get("PORT")
    if PORT is None:
        raise ValueError("PORT parameter missing in config")

    BAUDRATE = int(config.get("BAUDRATE", 9600))
    SLAVE_ID = int(config.get("SLAVE_ID", 1))
    RECONNECT_DELAY = float(config.get("RECONNECT_DELAY", 2.0))

    if registers_file is None:
        raise ValueError("REGISTERS_FILE parameter missing in config")

    debug = str_to_bool(config.get("DEBUG", "false"))

    if debug:
        print(f"Connecting to port {PORT}")

    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=0.5)
        if debug:
            print("Port opened successfully")
    except Exception as e:
        print(f"Error opening port: {e}")
        return {}

    with open(registers_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    REGISTERS = data.get("registers", [])

    data = {}

    for reg in REGISTERS:
        name = reg.get("name")
        address = reg.get("address")
        scale = reg.get("scale", 1)
        unit = reg.get("unit", "")

        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            vals = read_register(ser, SLAVE_ID, address)
            time.sleep(0.2)
            display = vals[0] if vals else None

            if display is not None:
                value = display * scale

                # rounding to eliminate 236.60000000000002
                if isinstance(value, float):
                    value = round(value, 1)

                text = f"{value} {unit}"
            else:
                value = None
                text = "No response/CRC error"

            data[name] = value

            if debug:
               print(f"{name}: {text}")
        except Exception as e:
            if debug:
                print(f"Error reading register {address} ({name}): {e}")
            data[name] = None

    ser.close()
    return data
