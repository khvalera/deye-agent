import time

# =================================
# RS485 / Modbus debug helpers
# =================================
def _hex_bytes(data):
    """Return bytes as a compact hexadecimal string for debug output."""
    if data is None:
        return ""
    return " ".join("{:02X}".format(value) for value in bytearray(data))


def _in_waiting(ser):
    """Read pyserial's pending RX byte count without allowing debug to fail."""
    try:
        return int(getattr(ser, "in_waiting", 0) or 0)
    except Exception:
        return -1


def _capture_stale_rx(ser):
    """Capture bytes that reset_input_buffer() is about to discard.

    This is used only for diagnostics. Reading these bytes is functionally
    equivalent to discarding them with reset_input_buffer(), but it gives us
    evidence if a delayed Modbus response arrives between requests/retries.
    """
    result = {
        "pending": _in_waiting(ser),
        "data": b"",
        "error": None,
    }

    if result["pending"] > 0:
        try:
            result["data"] = ser.read(result["pending"])
        except Exception as exc:
            result["error"] = str(exc)

    return result


# =================================
# CRC16 Modbus
# =================================
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


# =================================
# Modbus request
# =================================
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


# =================================
# Modbus response validation
# =================================
def _validate_response(resp, slave_id, count):
    """Validate one Modbus RTU 0x03 response before using its register data.

    A CRC-valid response is not sufficient by itself. We also require the
    expected slave id, function code and byte count. This prevents a complete
    but unrelated frame from being accepted as the value for this request.

    Returns:
        (True, "OK") for a valid frame.
        (False, reason) for a rejected frame.
    """
    expected_len = 5 + 2 * count
    expected_byte_count = 2 * count

    if len(resp) != expected_len:
        return False, "short/incomplete response ({}/{})".format(
            len(resp), expected_len
        )

    if resp[0] != slave_id:
        return False, "slave mismatch (received {}, expected {})".format(
            resp[0], slave_id
        )

    if resp[1] != 0x03:
        return False, "unexpected function 0x{:02X} (expected 0x03)".format(
            resp[1]
        )

    if resp[2] != expected_byte_count:
        return False, "byte count mismatch (received {}, expected {})".format(
            resp[2], expected_byte_count
        )

    received_crc = resp[-2:]
    calculated_crc = calc_crc(resp[:-2])
    if calculated_crc != received_crc:
        return False, "CRC mismatch"

    return True, "OK"


# =================================
# Reading one register with retry
# =================================
def read_register(
        ser,
        slave_id,
        reg_addr,
        count=1,
        debug=False,
        name="",
        stale_rx=None,
        max_attempts=3,
        retry_delay=0.2):
    """Read one Modbus register, retrying only after an invalid/missing frame.

    The retry is intentionally local to the same register. If one request or
    response is lost on RS485, we do not immediately advance to the next
    register. This avoids turning one transient timeout into misleading data.

    Important: a retry never weakens validation. Every attempt must pass the
    full length/slave/function/byte-count/CRC checks before data is returned.
    """
    if max_attempts < 1:
        max_attempts = 1
    if retry_delay < 0:
        retry_delay = 0

    req = build_request(slave_id, reg_addr, count)
    expected_len = 5 + 2 * count
    last_reason = "no attempt made"

    for attempt in range(1, max_attempts + 1):
        resp = b""
        started = None
        pending_before_inner_reset = None
        pending_after_inner_reset = None

        # On the first attempt the caller has already captured RX bytes before
        # its outer reset. On retry, capture any response that arrived late
        # during the retry delay, immediately before we resynchronise RX.
        attempt_stale_rx = stale_rx if attempt == 1 else None
        if attempt > 1 and debug:
            attempt_stale_rx = _capture_stale_rx(ser)

        try:
            if debug:
                pending_before_inner_reset = _in_waiting(ser)

            # Preserve the original project behaviour: clear both buffers
            # immediately before each Modbus request.
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            if debug:
                pending_after_inner_reset = _in_waiting(ser)

            started = time.time()
            ser.write(req)

            # Keep the existing 200 ms post-TX delay unchanged for fix v1.
            # We are deliberately not tuning transport timing in this patch.
            time.sleep(0.2)

            resp = ser.read(expected_len)
            finished = time.time()

            valid, reason = _validate_response(resp, slave_id, count)
            last_reason = reason

            if debug:
                elapsed_ms = (finished - started) * 1000.0
                print("RS485 DEBUG register={} ({}) attempt {}/{}".format(
                    reg_addr, name, attempt, max_attempts
                ))

                if attempt_stale_rx is not None:
                    print("  RX pending before reset: {} byte(s)".format(
                        attempt_stale_rx.get("pending", -1)
                    ))
                    if attempt_stale_rx.get("data"):
                        print("  STALE/LATE RX before reset: {}".format(
                            _hex_bytes(attempt_stale_rx.get("data"))
                        ))
                    if attempt_stale_rx.get("error"):
                        print("  STALE/LATE RX read error: {}".format(
                            attempt_stale_rx.get("error")
                        ))

                print("  RX pending before inner reset: {} byte(s)".format(
                    pending_before_inner_reset
                ))
                print("  RX pending after inner reset: {} byte(s)".format(
                    pending_after_inner_reset
                ))
                print("  TX: {}".format(_hex_bytes(req)))
                print("  RX expected/read: {}/{} byte(s)".format(
                    expected_len, len(resp)
                ))
                print("  RX: {}".format(_hex_bytes(resp)))
                print("  elapsed: {:.1f} ms".format(elapsed_ms))

                if len(resp) >= 1:
                    print("  slave: {} (expected {}){}".format(
                        resp[0], slave_id,
                        " OK" if resp[0] == slave_id else " MISMATCH"
                    ))

                if len(resp) >= 2:
                    print("  function: 0x{:02X}{}".format(
                        resp[1],
                        " OK" if resp[1] == 0x03 else " UNEXPECTED"
                    ))

                if len(resp) >= 3:
                    expected_byte_count = 2 * count
                    print("  byte_count: {} (expected {}){}".format(
                        resp[2], expected_byte_count,
                        " OK" if resp[2] == expected_byte_count else " MISMATCH"
                    ))

                if len(resp) >= 2:
                    received_crc = resp[-2:]
                    calculated_crc = calc_crc(resp[:-2])
                    print("  CRC received:   {}".format(
                        _hex_bytes(received_crc)
                    ))
                    print("  CRC calculated: {}{}".format(
                        _hex_bytes(calculated_crc),
                        " OK" if calculated_crc == received_crc else " MISMATCH"
                    ))

                extra = _in_waiting(ser)
                print("  RX pending after frame read: {} byte(s)".format(extra))
                if extra > 0:
                    try:
                        extra_data = ser.read(extra)
                        print("  EXTRA RX after frame: {}".format(
                            _hex_bytes(extra_data)
                        ))
                    except Exception as exc:
                        print("  EXTRA RX read error: {}".format(exc))

            if valid:
                byte_count = resp[2]
                values = []
                for i in range(byte_count // 2):
                    hi = resp[3 + 2 * i]
                    lo = resp[3 + 2 * i + 1]
                    values.append((hi << 8) | lo)

                if debug:
                    print("  RAW values: {}".format(values))
                    print("  RESULT: accepted")

                return values

            if debug:
                print("  RESULT: rejected - {}".format(reason))

        except Exception as exc:
            last_reason = "exception: {}".format(exc)
            if debug:
                print("RS485 DEBUG register={} ({}) attempt {}/{}".format(
                    reg_addr, name, attempt, max_attempts
                ))
                print("  RESULT: exception - {}".format(exc))
                print("  TX was: {}".format(_hex_bytes(req)))
                if resp:
                    print("  RX was: {}".format(_hex_bytes(resp)))

        if attempt < max_attempts:
            if debug:
                print("  RETRY: same register after {:.3f} s".format(
                    retry_delay
                ))

            # Give a delayed response a short window to arrive. The next
            # attempt will capture it in debug mode and then clear RX before
            # sending a fresh request for exactly the same register.
            time.sleep(retry_delay)

    if debug:
        print("RS485 DEBUG register={} ({}) FINAL: failed after {} attempt(s): {}".format(
            reg_addr, name, max_attempts, last_reason
        ))

    return None


# =================================
# Read Deye data function
# =================================
def read_deye_data(config, str_to_bool, registers_file):
    import serial
    import yaml

    PORT = config.get("PORT")
    if PORT is None:
        raise ValueError("PORT parameter missing in config")

    BAUDRATE = int(config.get("BAUDRATE", 9600))
    SLAVE_ID = int(config.get("SLAVE_ID", 1))
    RECONNECT_DELAY = float(config.get("RECONNECT_DELAY", 2.0))

    # Optional RS485 reliability settings. Existing configurations need no
    # changes: fix v1 uses three attempts with a 200 ms delay by default.
    READ_ATTEMPTS = int(config.get("READ_ATTEMPTS", 3))
    RETRY_DELAY = float(config.get("RETRY_DELAY", 0.2))

    if READ_ATTEMPTS < 1:
        READ_ATTEMPTS = 1
    if RETRY_DELAY < 0:
        RETRY_DELAY = 0

    if registers_file is None:
        raise ValueError("REGISTERS_FILE parameter missing in config")

    debug = str_to_bool(config.get("DEBUG", "false"))

    if debug:
        print("Connecting to port {}".format(PORT))

    try:
        # POSIX exclusive mode prevents a second new deye-agent process from
        # opening the same serial device while this process owns it. This is
        # important because two Modbus masters on one /dev/ttyUSB* can consume
        # each other's valid responses and produce believable but wrong data.
        ser = serial.Serial(
            PORT,
            BAUDRATE,
            timeout=0.5,
            exclusive=True
        )
        if debug:
            print("Port opened successfully (exclusive mode)")
    except Exception as e:
        print("Error opening port: {}".format(e))
        return {}

    with open(registers_file, encoding="utf-8") as f:
        register_config = yaml.safe_load(f)
    REGISTERS = register_config.get("registers", [])

    data = {}

    for reg in REGISTERS:
        name = reg.get("name")
        address = reg.get("address")
        scale = reg.get("scale", 1)
        unit = reg.get("unit", "")

        try:
            # Diagnostic only: these bytes are exactly what the existing
            # reset_input_buffer() below would discard anyway.
            stale_rx = _capture_stale_rx(ser) if debug else None

            # Keep the original outer reset behaviour unchanged for fix v1.
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            vals = read_register(
                ser,
                SLAVE_ID,
                address,
                debug=debug,
                name=name,
                stale_rx=stale_rx,
                max_attempts=READ_ATTEMPTS,
                retry_delay=RETRY_DELAY
            )

            # Keep the original delay between register reads unchanged.
            time.sleep(0.2)
            display = vals[0] if vals else None

            if display is not None:
                value = display * scale

                # Round floating-point values such as 236.60000000000002.
                if isinstance(value, float):
                    value = round(value, 1)

                text = "{} {}".format(value, unit)
            else:
                value = None
                text = "No response/invalid Modbus frame after retries"

            data[name] = value

            if debug:
                print("{}: {}".format(name, text))
        except Exception as e:
            if debug:
                print("Error reading register {} ({}): {}".format(
                    address, name, e
                ))
            data[name] = None

    ser.close()
    return data
