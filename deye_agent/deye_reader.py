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
# Register value decoding
# =================================
def _decode_register_value(values, value_type, count):
    """Decode a configured value from Modbus 16-bit register words.

    Supported types:
        uint16: unsigned 16-bit integer
        int16: signed 16-bit integer
        uint32: unsigned 32-bit integer, low word first
        int32: signed 32-bit integer, low word first
        bool_any_nonzero: True if any configured 16-bit word is non-zero

    Legacy aliases "int" and "float" preserve the project's previous unsigned
    single-register behaviour. Scaling is applied later, so legacy "float"
    does not mean an IEEE-754 Modbus float.

    For 32-bit values the YAML register definition must explicitly supply the
    two protocol words in low-word, high-word order. The addresses may be
    contiguous or non-contiguous.
    """
    if not values:
        return None

    normalized_type = str(value_type or "uint16").strip().lower()

    if normalized_type in ("uint16", "int16", "int", "float"):
        if count != 1:
            raise ValueError(
                "type '{}' requires count=1; got count={}".format(
                    normalized_type,
                    count
                )
            )

        raw = values[0]

        if normalized_type == "int16":
            return raw - 0x10000 if raw & 0x8000 else raw

        return raw

    if normalized_type in ("uint32", "int32"):
        if count != 2:
            raise ValueError(
                "type '{}' requires exactly two words; got count={}".format(
                    normalized_type,
                    count
                )
            )

        low_word = values[0] & 0xFFFF
        high_word = values[1] & 0xFFFF
        raw = (high_word << 16) | low_word

        if normalized_type == "int32" and raw & 0x80000000:
            return raw - 0x100000000

        return raw

    if normalized_type == "bool_any_nonzero":
        # Generic status aggregation for one or more raw Modbus words.
        # True means at least one configured word is non-zero.
        return any((int(value) & 0xFFFF) != 0 for value in values)

    raise ValueError(
        "Unsupported register type '{}'. Supported types: "
        "uint16, int16, uint32, int32, bool_any_nonzero, int, float"
        .format(value_type)
    )


# =================================
# Register value transformation
# =================================
def _transform_register_value(value, scale=1, offset=0, precision=None):
    """Apply YAML scale, offset and optional decimal precision.

    The transformation order is:

        decoded_value * scale + offset

    Examples:
        Battery temperature register 182:
            raw 1200 * 0.1 - 100.0 = 20.0 C

        Battery voltage register 183:
            raw 5234 * 0.01 = 52.34 V

    If precision is omitted, the previous project behaviour is preserved:
    floating-point values are rounded to one decimal place.
    """
    if value is None:
        return None

    result = value * scale + offset

    if precision is not None:
        precision = int(precision)
        if precision < 0:
            raise ValueError("precision must be >= 0")
        return round(result, precision)

    if isinstance(result, float):
        return round(result, 1)

    return result


# =================================
# Read Deye data function
# =================================
def _prepare_read_blocks(register_config, debug=False):
    """Validate optional YAML read_blocks configuration.

    A read block describes one contiguous Modbus 0x03 request. Registers inside
    the block are still decoded according to their own YAML definitions.

    Invalid block configuration does not disable inverter reading. Instead,
    block mode is disabled and the reader falls back to the established
    individual-register path.
    """
    raw_blocks = register_config.get("read_blocks", []) or []
    blocks = []
    used_addresses = set()

    try:
        for index, block in enumerate(raw_blocks):
            start = int(block.get("start"))
            count = int(block.get("count"))
            name = block.get(
                "name",
                "Block {}-{}".format(start, start + count - 1)
            )

            if start < 0 or start > 0xFFFF:
                raise ValueError(
                    "read_blocks[{}] start is outside Modbus range".format(index)
                )

            if count < 1:
                raise ValueError(
                    "read_blocks[{}] count must be >= 1".format(index)
                )

            if start + count - 1 > 0xFFFF:
                raise ValueError(
                    "read_blocks[{}] exceeds Modbus address range".format(index)
                )

            addresses = set(range(start, start + count))
            overlap = used_addresses.intersection(addresses)

            if overlap:
                raise ValueError(
                    "read_blocks overlap at register(s): {}".format(
                        ", ".join(str(value) for value in sorted(overlap))
                    )
                )

            used_addresses.update(addresses)

            blocks.append({
                "name": name,
                "start": start,
                "count": count,
            })

    except Exception as exc:
        if debug:
            print(
                "Invalid read_blocks configuration: {}. "
                "Using individual register reads.".format(exc)
            )
        return []

    return blocks


def _read_device_values(
        ser,
        slave_id,
        address,
        count,
        name,
        debug,
        read_attempts,
        retry_delay):
    """Read one Modbus request using the established transport behaviour."""
    # Diagnostic only: capture bytes that the existing outer RX reset would
    # otherwise discard.
    stale_rx = _capture_stale_rx(ser) if debug else None

    # Preserve the original outer reset behaviour before every Modbus request.
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    values = read_register(
        ser,
        slave_id,
        address,
        count=count,
        debug=debug,
        name=name,
        stale_rx=stale_rx,
        max_attempts=read_attempts,
        retry_delay=retry_delay
    )

    # Preserve the established delay between Modbus requests. In block mode
    # this delay occurs once per block rather than once per configured metric.
    time.sleep(0.2)

    return values


def _resolve_register_addresses(reg):
    """Return the Modbus word addresses required by one YAML metric.

    Normal scalar/contiguous definitions use:
        address: 72
        count: 2

    Protocol values whose low/high words are not adjacent can use:
        addresses: [78, 80]

    The order in "addresses" is significant and must match the word order
    expected by the configured type. For Deye uint32 energy counters this is
    low word first, high word second.
    """
    explicit_addresses = reg.get("addresses")

    if explicit_addresses is not None:
        if not isinstance(explicit_addresses, (list, tuple)):
            raise ValueError("addresses must be a list")

        addresses = [int(value) for value in explicit_addresses]

        if not addresses:
            raise ValueError("addresses must not be empty")

        return addresses

    address = reg.get("address")
    if address is None:
        raise ValueError("address or addresses is required")

    address = int(address)
    count = int(reg.get("count", 1))

    if count < 1:
        raise ValueError("count must be >= 1")

    return list(range(address, address + count))


def _addresses_are_contiguous(addresses):
    """Return True when addresses form one ascending contiguous Modbus range."""
    if not addresses:
        return False

    first = addresses[0]
    return addresses == list(range(first, first + len(addresses)))


def _apply_bit_field(value, mask=None, shift=0):
    """Extract an optional bit field from a decoded integer value.

    YAML examples:

        mask: 15
        shift: 0

        mask: 240
        shift: 4

    The bit field is extracted before scale/offset/precision and value_map are
    applied. This keeps protocol-specific packed status registers declarative
    in registers.yaml instead of hard-coding them in the Python reader.
    """
    if value is None or mask is None:
        return value

    if isinstance(mask, str):
        mask = int(mask, 0)
    else:
        mask = int(mask)

    shift = int(shift)

    if mask < 0:
        raise ValueError("mask must be >= 0")
    if shift < 0:
        raise ValueError("shift must be >= 0")

    return (int(value) & mask) >> shift


def _apply_value_map(value, value_map):
    """Map a decoded numeric value to a human-readable YAML label.

    Numeric YAML keys are preferred, but string keys are accepted as well.
    Unknown values are returned unchanged so future firmware states remain
    visible instead of being silently discarded.
    """
    if not value_map:
        return value

    if value in value_map:
        return value_map[value]

    string_key = str(value)
    if string_key in value_map:
        return value_map[string_key]

    return value


def _read_deye_data_from_serial(
        ser,
        config,
        str_to_bool,
        registers_file):
    """Read telemetry using an already-open serial session.

    This is the same telemetry implementation used by read_deye_data().
    Snapshot v2 reuses it so there is only one telemetry decoder/read path.
    """
    import yaml

    SLAVE_ID = int(config.get("SLAVE_ID", 1))
    READ_ATTEMPTS = int(config.get("READ_ATTEMPTS", 3))
    RETRY_DELAY = float(config.get("RETRY_DELAY", 0.2))

    if READ_ATTEMPTS < 1:
        READ_ATTEMPTS = 1
    if RETRY_DELAY < 0:
        RETRY_DELAY = 0

    if registers_file is None:
        raise ValueError("REGISTERS_FILE parameter missing in config")

    debug = str_to_bool(config.get("DEBUG", "false"))

    with open(registers_file, encoding="utf-8") as f:
        register_config = yaml.safe_load(f) or {}

    REGISTERS = register_config.get("registers", []) or []
    READ_BLOCKS = _prepare_read_blocks(register_config, debug=debug)

    # Raw scalar values obtained from successful block reads are cached by
    # their absolute Modbus register address.
    block_value_cache = {}

    if READ_BLOCKS and debug:
        print(
            "Block read mode enabled: {} block(s)".format(
                len(READ_BLOCKS)
            )
        )

    # -------------------------------------------------------------
    # Phase 1: read configured contiguous blocks.
    # -------------------------------------------------------------
    for block in READ_BLOCKS:
        start = block["start"]
        count = block["count"]
        name = block["name"]

        values = _read_device_values(
            ser,
            SLAVE_ID,
            start,
            count,
            name,
            debug,
            READ_ATTEMPTS,
            RETRY_DELAY
        )

        if values is None or len(values) != count:
            if debug:
                print(
                    "BLOCK FALLBACK: {} failed; affected configured "
                    "registers will be read individually.".format(name)
                )
            continue

        for offset, raw_value in enumerate(values):
            block_value_cache[start + offset] = raw_value

        if debug:
            print(
                "BLOCK CACHE: {} stored {} register value(s)".format(
                    name,
                    len(values)
                )
            )

    # -------------------------------------------------------------
    # Phase 2: decode metrics in YAML order.
    #
    # A scalar register covered by a successful block is decoded from
    # cache. Registers outside blocks, multi-register definitions, or
    # registers from a failed block use the original individual read path.
    # -------------------------------------------------------------
    data = {}

    for reg in REGISTERS:
        name = reg.get("name")
        scale = reg.get("scale", 1)
        offset = reg.get("offset", 0)
        precision = reg.get("precision")
        unit = reg.get("unit", "")
        value_type = reg.get("type", "uint16")
        value_map = reg.get("value_map")
        mask = reg.get("mask")
        shift = reg.get("shift", 0)

        addresses = []

        try:
            addresses = _resolve_register_addresses(reg)
            count = len(addresses)
            address = addresses[0]

            # Prefer values already obtained from successful block reads.
            # This works for both scalar registers and 32-bit counters,
            # including non-contiguous word pairs such as Deye 78/80.
            if all(
                word_address in block_value_cache
                for word_address in addresses
            ):
                vals = [
                    block_value_cache[word_address]
                    for word_address in addresses
                ]

                if debug:
                    print(
                        "BLOCK VALUE register(s)={} ({}) RAW values: {}"
                        .format(
                            ",".join(str(value) for value in addresses),
                            name,
                            vals
                        )
                    )

            # If all words are contiguous, preserve one normal Modbus read.
            elif _addresses_are_contiguous(addresses):
                vals = _read_device_values(
                    ser,
                    SLAVE_ID,
                    addresses[0],
                    count,
                    name,
                    debug,
                    READ_ATTEMPTS,
                    RETRY_DELAY
                )

            # Explicit non-contiguous words cannot be requested as one
            # Modbus range without also including unrelated registers.
            # Read only the required words individually as a safe fallback.
            else:
                vals = []

                if debug:
                    print(
                        "WORD READ register(s)={} ({})"
                        .format(
                            ",".join(str(value) for value in addresses),
                            name
                        )
                    )

                for word_address in addresses:
                    word_values = _read_device_values(
                        ser,
                        SLAVE_ID,
                        word_address,
                        1,
                        name,
                        debug,
                        READ_ATTEMPTS,
                        RETRY_DELAY
                    )

                    if not word_values:
                        vals = None
                        break

                    vals.append(word_values[0])

            display = _decode_register_value(
                vals,
                value_type,
                count
            )

            if display is not None:
                display = _apply_bit_field(
                    display,
                    mask=mask,
                    shift=shift
                )

                if isinstance(display, bool):
                    # Preserve status aggregates as JSON booleans.
                    value = display
                else:
                    numeric_value = _transform_register_value(
                        display,
                        scale=scale,
                        offset=offset,
                        precision=precision
                    )

                    value = _apply_value_map(
                        numeric_value,
                        value_map
                    )

                if unit:
                    text_value = "{} {}".format(value, unit)
                else:
                    text_value = str(value)
            else:
                value = None
                text_value = "No response/invalid Modbus frame after retries"

            data[name] = value

            if debug:
                print("{}: {}".format(name, text_value))

        except Exception as e:
            if debug:
                address_text = (
                    ",".join(str(value) for value in addresses)
                    if addresses
                    else "unknown"
                )
                print(
                    "Error reading register(s) {} ({}): {}".format(
                        address_text,
                        name,
                        e
                    )
                )
            data[name] = None

    return data


def read_deye_data(config, str_to_bool, registers_file):
    """Read telemetry using the established one-reader serial session."""
    import serial

    port = config.get("PORT")
    if port is None:
        raise ValueError("PORT parameter missing in config")

    baudrate = int(config.get("BAUDRATE", 9600))
    debug = str_to_bool(config.get("DEBUG", "false"))

    if debug:
        print("Connecting to port {}".format(port))

    try:
        ser = serial.Serial(
            port,
            baudrate,
            timeout=0.5,
            exclusive=True
        )

        if debug:
            print("Port opened successfully (exclusive mode)")

    except Exception as exc:
        # Preserve historical public-reader behavior.
        print("Error opening port: {}".format(exc))
        return {}

    try:
        return _read_deye_data_from_serial(
            ser,
            config,
            str_to_bool,
            registers_file
        )
    finally:
        ser.close()


def _validate_raw_register_range(start, count):
    """Validate one Modbus holding-register range."""
    start = int(start)
    count = int(count)

    if start < 0 or start > 0xFFFF:
        raise ValueError("start register must be between 0 and 65535")

    if count < 1 or count > 125:
        raise ValueError("count must be between 1 and 125")

    if start + count - 1 > 0xFFFF:
        raise ValueError(
            "requested register range exceeds address 65535"
        )

    return start, count


def _read_raw_registers_from_serial(
        ser,
        config,
        str_to_bool,
        start,
        count,
        name=None):
    """Read one raw range through an already-open serial session."""
    start, count = _validate_raw_register_range(start, count)

    slave_id = int(config.get("SLAVE_ID", 1))
    read_attempts = int(config.get("READ_ATTEMPTS", 3))
    retry_delay = float(config.get("RETRY_DELAY", 0.2))
    debug = str_to_bool(config.get("DEBUG", "false"))

    if read_attempts < 1:
        read_attempts = 1
    if retry_delay < 0:
        retry_delay = 0

    if name is None:
        name = "Raw registers {}-{}".format(
            start,
            start + count - 1
        )

    return _read_device_values(
        ser,
        slave_id,
        start,
        count,
        name,
        debug,
        read_attempts,
        retry_delay
    )


def read_raw_registers(config, str_to_bool, start, count):
    """Read a raw Modbus holding-register range from the inverter.

    Public behavior remains one call / one exclusive serial session.
    Snapshot v2 uses _read_raw_registers_from_serial() internally.
    """
    import serial

    start, count = _validate_raw_register_range(start, count)

    port = config.get("PORT")
    if port is None:
        raise ValueError("PORT parameter missing in config")

    baudrate = int(config.get("BAUDRATE", 9600))
    debug = str_to_bool(config.get("DEBUG", "false"))

    if debug:
        print("Connecting to port {}".format(port))

    try:
        ser = serial.Serial(
            port,
            baudrate,
            timeout=0.5,
            exclusive=True
        )

        if debug:
            print("Port opened successfully (exclusive mode)")

    except Exception as exc:
        raise RuntimeError(
            "Error opening port: {}".format(exc)
        )

    try:
        return _read_raw_registers_from_serial(
            ser,
            config,
            str_to_bool,
            start,
            count
        )
    finally:
        ser.close()


def _build_inventory_register(address, value=None, readable=True):
    """Build one stable raw inventory row."""
    address = int(address)

    if not readable:
        return {
            "address": address,
            "address_hex": "0x{:04X}".format(address),
            "status": "no_response_after_retries",
            "uint16": None,
            "int16": None,
            "hex": None,
            "zero": None,
        }

    unsigned_value = int(value) & 0xFFFF
    signed_value = (
        unsigned_value - 0x10000
        if unsigned_value & 0x8000
        else unsigned_value
    )

    return {
        "address": address,
        "address_hex": "0x{:04X}".format(address),
        "status": "readable",
        "uint16": unsigned_value,
        "int16": signed_value,
        "hex": "0x{:04X}".format(unsigned_value),
        "zero": unsigned_value == 0,
    }


def _scan_inventory_range(
        read_func,
        start,
        end,
        chunk_size=47,
        min_chunk_size=8,
        progress_callback=None):
    """Scan one inclusive register range with bounded adaptive splitting.

    Fast mode stops splitting a failed block once its size is at or below
    ``min_chunk_size``. Those addresses are marked as
    ``block_no_response_after_retries`` because they were not individually
    tested.

    Set min_chunk_size=1 for an exhaustive/deep scan.
    """
    start = int(start)
    end = int(end)
    chunk_size = int(chunk_size)
    min_chunk_size = int(min_chunk_size)

    if start < 0 or end < start or end > 0xFFFF:
        raise ValueError(
            "invalid inventory range {}..{}".format(start, end)
        )

    if chunk_size < 1 or chunk_size > 125:
        raise ValueError(
            "inventory chunk_size must be between 1 and 125"
        )

    if min_chunk_size < 1 or min_chunk_size > chunk_size:
        raise ValueError(
            "inventory min_chunk_size must be between 1 and chunk_size"
        )

    rows = []
    total = end - start + 1
    completed = [0]
    probes = [0]

    def report(segment_start, segment_count, status, depth):
        if progress_callback is None:
            return

        progress_callback({
            "start": segment_start,
            "end": segment_start + segment_count - 1,
            "count": segment_count,
            "status": status,
            "depth": depth,
            "completed": completed[0],
            "total": total,
            "probes": probes[0],
        })

    def add_failed_segment(segment_start, segment_count):
        status = (
            "no_response_after_retries"
            if segment_count == 1
            else "block_no_response_after_retries"
        )

        for offset in range(segment_count):
            row = _build_inventory_register(
                segment_start + offset,
                readable=False
            )
            row["status"] = status
            row["probe_start"] = segment_start
            row["probe_count"] = segment_count
            rows.append(row)

        completed[0] += segment_count

    def scan_segment(segment_start, segment_count, depth):
        probes[0] += 1
        values = read_func(segment_start, segment_count)

        if values is not None and len(values) == segment_count:
            for offset, value in enumerate(values):
                rows.append(
                    _build_inventory_register(
                        segment_start + offset,
                        value=value,
                        readable=True
                    )
                )

            completed[0] += segment_count
            report(
                segment_start,
                segment_count,
                "readable",
                depth
            )
            return

        if segment_count <= min_chunk_size:
            add_failed_segment(segment_start, segment_count)
            report(
                segment_start,
                segment_count,
                "failed-terminal",
                depth
            )
            return

        report(
            segment_start,
            segment_count,
            "split",
            depth
        )

        left_count = segment_count // 2
        right_count = segment_count - left_count

        scan_segment(
            segment_start,
            left_count,
            depth + 1
        )
        scan_segment(
            segment_start + left_count,
            right_count,
            depth + 1
        )

    current = start

    while current <= end:
        count = min(
            chunk_size,
            end - current + 1
        )

        scan_segment(
            current,
            count,
            0
        )

        current += count

    rows.sort(key=lambda item: item["address"])

    return {
        "registers": rows,
        "probes": probes[0],
    }


def _summarize_inventory(registers):
    """Return stable counts for one inventory result."""
    total = len(registers)

    readable = sum(
        1 for row in registers
        if row["status"] == "readable"
    )

    no_response = sum(
        1 for row in registers
        if row["status"] == "no_response_after_retries"
    )

    block_no_response = sum(
        1 for row in registers
        if row["status"] == "block_no_response_after_retries"
    )

    zero = sum(
        1 for row in registers
        if row["status"] == "readable"
        and row["zero"] is True
    )

    nonzero = sum(
        1 for row in registers
        if row["status"] == "readable"
        and row["zero"] is False
    )

    return {
        "requested": total,
        "readable": readable,
        "no_response_after_retries": no_response,
        "block_no_response_after_retries": block_no_response,
        "zero": zero,
        "nonzero": nonzero,
    }


def read_register_inventory(
        config,
        str_to_bool,
        ranges,
        chunk_size=47,
        min_chunk_size=8,
        profile_name=None,
        progress_callback=None):
    """Read a raw register inventory using Modbus function 0x03 only.

    Inventory discovery uses its own retry count
    (INVENTORY_READ_ATTEMPTS, default 1) so broad scans stay bounded when a
    firmware-specific region does not respond.

    The serial port remains open for the complete scan.
    """
    import serial

    normalized_ranges = []

    for item in ranges or []:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(
                "inventory ranges must contain [start, end] pairs"
            )

        range_start = int(item[0])
        range_end = int(item[1])

        if (
                range_start < 0
                or range_end < range_start
                or range_end > 0xFFFF):
            raise ValueError(
                "invalid inventory range {}..{}".format(
                    range_start,
                    range_end
                )
            )

        normalized_ranges.append([
            range_start,
            range_end
        ])

    if not normalized_ranges:
        raise ValueError(
            "no inventory ranges configured for this profile"
        )

    chunk_size = int(chunk_size)
    min_chunk_size = int(min_chunk_size)

    if chunk_size < 1 or chunk_size > 125:
        raise ValueError(
            "inventory chunk_size must be between 1 and 125"
        )

    if min_chunk_size < 1 or min_chunk_size > chunk_size:
        raise ValueError(
            "inventory min_chunk_size must be between 1 and chunk_size"
        )

    port = config.get("PORT")
    if port is None:
        raise ValueError(
            "PORT parameter missing in config"
        )

    baudrate = int(
        config.get("BAUDRATE", 9600)
    )
    slave_id = int(
        config.get("SLAVE_ID", 1)
    )

    read_attempts = int(
        config.get(
            "INVENTORY_READ_ATTEMPTS",
            1
        )
    )

    retry_delay = float(
        config.get("RETRY_DELAY", 0.2)
    )

    debug = str_to_bool(
        config.get("DEBUG", "false")
    )

    if read_attempts < 1:
        read_attempts = 1

    if retry_delay < 0:
        retry_delay = 0

    if debug:
        print(
            "Connecting to port {}".format(
                port
            )
        )

        print(
            "Read-only inventory ranges: {}".format(
                ", ".join(
                    "{}-{}".format(
                        item[0],
                        item[1]
                    )
                    for item in normalized_ranges
                )
            )
        )

    try:
        ser = serial.Serial(
            port,
            baudrate,
            timeout=0.5,
            exclusive=True
        )
    except Exception as exc:
        raise RuntimeError(
            "Error opening port: {}".format(
                exc
            )
        )

    try:
        all_rows = []
        total_probes = 0

        def read_func(address, count):
            return _read_device_values(
                ser,
                slave_id,
                address,
                count,
                "Inventory registers {}-{}".format(
                    address,
                    address + count - 1
                ),
                debug,
                read_attempts,
                retry_delay
            )

        for range_start, range_end in normalized_ranges:
            scanned = _scan_inventory_range(
                read_func,
                range_start,
                range_end,
                chunk_size=chunk_size,
                min_chunk_size=min_chunk_size,
                progress_callback=progress_callback
            )

            all_rows.extend(
                scanned["registers"]
            )

            total_probes += scanned["probes"]

        all_rows.sort(
            key=lambda item: item["address"]
        )

        return {
            "profile": profile_name,
            "function_code": "0x03",
            "read_only": True,
            "scan_mode": (
                "deep"
                if min_chunk_size == 1
                else "fast"
            ),
            "chunk_size": chunk_size,
            "min_chunk_size": min_chunk_size,
            "inventory_read_attempts": read_attempts,
            "ranges": [
                {
                    "start": item[0],
                    "end": item[1]
                }
                for item in normalized_ranges
            ],
            "probes": total_probes,
            "summary": _summarize_inventory(
                all_rows
            ),
            "registers": all_rows,
        }
    finally:
        ser.close()



def _decode_binary_setting(value):
    """Decode a documented 0/1 setting without hiding unexpected raw values."""
    value = int(value) & 0xFFFF

    if value == 0:
        return False
    if value == 1:
        return True

    return None


def _decode_hhmm_setting(value):
    """Decode a Deye HHMM register such as 100 -> 01:00."""
    value = int(value) & 0xFFFF
    hour = value // 100
    minute = value % 100

    if hour > 23 or minute > 59:
        return None

    return "{:02d}:{:02d}".format(hour, minute)


def _decode_nibble_enable(code):
    """Decode a documented nibble where 0=disable and 1=enable."""
    code = int(code) & 0x0F

    if code == 0:
        return False
    if code == 1:
        return True

    return None


def _decode_signed16_setting(value):
    """Decode one documented signed 16-bit settings value."""
    value = int(value) & 0xFFFF
    return value - 0x10000 if value & 0x8000 else value



def _raw_setting_word(address, value, reason=None):
    """Build one stable raw settings word without inventing semantics."""
    unsigned = int(value) & 0xFFFF
    signed = (
        unsigned - 0x10000
        if unsigned & 0x8000
        else unsigned
    )

    result = {
        "address": int(address),
        "raw": unsigned,
        "raw_hex": _format_hex16(unsigned),
        "int16": signed,
    }

    if reason is not None:
        result["reason"] = reason

    return result


def decode_extended_settings(values):
    """Decode conservative single-phase settings from registers 326..416.

    Only California voltage/frequency ride-through fields 331..350 are
    semantically decoded. Those values match both V118 definitions and the
    validated 5 kW single-phase storage inverter capture.

    Registers 326..330 remain raw because the table is incomplete/variant
    sensitive and register 330 contains undocumented bits on the tested
    firmware.

    Registers 351..416 remain raw/unvalidated. The tested firmware conflicts
    with V118 in this area: several values exceed documented ranges, registers
    documented as reserved are non-zero, and documented 0/1 Wind-input enable
    fields contain other values. No semantic interpretation is invented.
    """
    if values is None or len(values) < 91:
        raise ValueError(
            "extended settings require registers 326 through 416"
        )

    raw = [int(value) & 0xFFFF for value in values[:91]]

    def word(address):
        return raw[address - 326]

    lhvrt_enable_raw = word(331)
    lhf_rt_enable_raw = word(342)

    lhvrt_voltages_raw = {
        "high_2": word(332),
        "high_1": word(333),
        "low_1": word(334),
        "low_2": word(335),
        "low_3": word(336),
    }

    lhvrt_times_raw = {
        "high_2": word(337),
        "high_1": word(338),
        "low_1": word(339),
        "low_2": word(340),
        "low_3": word(341),
    }

    lhf_rt_frequencies_raw = {
        "high_2": word(343),
        "high_1": word(344),
        "low_1": word(345),
        "low_2": word(346),
    }

    lhf_rt_times_raw = {
        "high_2": word(347),
        "high_1": word(348),
        "low_1": word(349),
        "low_2": word(350),
    }

    lhvrt_issues = []

    if _decode_binary_setting(lhvrt_enable_raw) is None:
        lhvrt_issues.append(
            "register 331 is outside the documented 0/1 enable encoding"
        )

    for name, value in lhvrt_voltages_raw.items():
        if value < 1000 or value > 3000:
            lhvrt_issues.append(
                "{} voltage raw {} is outside V118 range 1000..3000".format(
                    name,
                    value
                )
            )

    for name, value in lhvrt_times_raw.items():
        if value < 0 or value > 300:
            lhvrt_issues.append(
                "{} time raw {} is outside V118 range 0..300".format(
                    name,
                    value
                )
            )

    lhf_rt_issues = []

    if _decode_binary_setting(lhf_rt_enable_raw) is None:
        lhf_rt_issues.append(
            "register 342 cannot be decoded as a 0/1 enable value"
        )

    for name, value in lhf_rt_frequencies_raw.items():
        if value < 4500 or value > 6500:
            lhf_rt_issues.append(
                "{} frequency raw {} is outside V118 range 4500..6500".format(
                    name,
                    value
                )
            )

    for name, value in lhf_rt_times_raw.items():
        if value < 0 or value > 300:
            lhf_rt_issues.append(
                "{} time raw {} is outside V118 range 0..300".format(
                    name,
                    value
                )
            )

    raw_prefix = []

    for address in range(326, 331):
        reason = (
            "No stable semantic mapping is assigned for this firmware"
            if address < 330
            else (
                "V118 documents communication-board setting bits, but the "
                "tested firmware has additional undocumented bits; raw only"
            )
        )
        raw_prefix.append(
            _raw_setting_word(
                address,
                word(address),
                reason
            )
        )

    unvalidated_tail = []

    for address in range(351, 417):
        unvalidated_tail.append(
            _raw_setting_word(
                address,
                word(address)
            )
        )

    nonzero_tail = [
        item
        for item in unvalidated_tail
        if item["raw"] != 0
    ]

    return {
        "available": True,
        "register_range": {
            "start": 326,
            "end": 416,
            "count": 91,
        },

        "raw_only_326_330": raw_prefix,

        "california_voltage_ride_through": {
            "enable": {
                "raw": lhvrt_enable_raw,
                "raw_hex": _format_hex16(lhvrt_enable_raw),
                "enabled": _decode_binary_setting(lhvrt_enable_raw),
            },
            "voltage_v": {
                key: round(value * 0.1, 1)
                for key, value in lhvrt_voltages_raw.items()
            },
            "voltage_raw": lhvrt_voltages_raw,
            "time_setting_raw": lhvrt_times_raw,
            "time_note": (
                "V118 documents range 0..300 and explicitly states that "
                "raw 0 represents 0.16 s; other raw values are preserved "
                "without converting them to seconds"
            ),
            "validation": {
                "status": (
                    "match"
                    if not lhvrt_issues
                    else "conflict"
                ),
                "issues": lhvrt_issues,
            },
        },

        "california_frequency_ride_through": {
            "enable": {
                "raw": lhf_rt_enable_raw,
                "raw_hex": _format_hex16(lhf_rt_enable_raw),
                "enabled": _decode_binary_setting(lhf_rt_enable_raw),
            },
            "frequency_hz": {
                key: round(value * 0.01, 2)
                for key, value in lhf_rt_frequencies_raw.items()
            },
            "frequency_raw": lhf_rt_frequencies_raw,
            "time_setting_raw": lhf_rt_times_raw,
            "validation": {
                "status": (
                    "match"
                    if not lhf_rt_issues
                    else "partial"
                ),
                "issues": lhf_rt_issues,
            },
        },

        "raw_unvalidated_351_416": {
            "reason": (
                "Semantic decoding is intentionally disabled because the "
                "validated 5 kW single-phase storage inverter capture conflicts with V118 in this area. "
                "Examples include out-of-range slope/response values, "
                "non-zero values in documented reserved registers, and "
                "non-binary values in documented Wind-input enable fields."
            ),
            "zero_count": sum(
                1
                for item in unvalidated_tail
                if item["raw"] == 0
            ),
            "nonzero_count": len(nonzero_tail),
            "registers": unvalidated_tail,
        },
    }



def decode_settings(values, extended_values=None):
    """Decode validated single-phase storage settings.

    Preferred input is registers 197..296 (100 words). For compatibility with
    read-only settings v1, a 52-word 245..296 snapshot is still accepted and
    returns the original v1 fields without the extended battery/generator
    sections.

    V118 is used as the primary semantic source for 200..296. Ambiguous or
    undocumented fields are preserved as raw words instead of guessed.
    """
    if values is None:
        raise ValueError("settings require register values")

    if len(values) >= 100:
        base_address = 197
        raw = [int(value) & 0xFFFF for value in values[:100]]
        extended = True
    elif len(values) >= 52:
        base_address = 245
        raw = [int(value) & 0xFFFF for value in values[:52]]
        extended = False
    else:
        raise ValueError(
            "settings require registers 197 through 296 "
            "or legacy registers 245 through 296"
        )

    def word(address):
        index = address - base_address

        if index < 0 or index >= len(raw):
            raise ValueError(
                "register {} is not present in this settings snapshot".format(
                    address
                )
            )

        return raw[index]

    result = {
        "read_only": True,
        "register_range": {
            "start": base_address,
            "end": base_address + len(raw) - 1,
            "count": len(raw),
        },
    }

    undecoded_raw = {}

    if extended:
        control_mode_code = word(200)
        operating_basis_code = word(213)
        lithium_wake_raw = word(214)
        solar_input_code = word(233)
        force_generator_raw = word(234)
        generator_port_mode_code = word(235)
        pwm_test_raw = word(240)
        energy_management_code = word(243)
        limit_control_code = word(244)

        result["battery_configuration"] = {
            "control_mode": {
                "raw": control_mode_code,
                "raw_hex": _format_hex16(control_mode_code),
                "mode": {
                    0: "Lead-battery four-stage charging",
                    1: "Lithium battery",
                }.get(control_mode_code),
            },
            "equalization_voltage_v": round(word(201) * 0.01, 2),
            "absorption_voltage_v": round(word(202) * 0.01, 2),
            "float_voltage_v": round(word(203) * 0.01, 2),
            "capacity_ah": word(204),
            "empty_voltage_v": round(word(205) * 0.01, 2),
            "zero_export_power_raw": word(206),
            "zero_export_power_raw_hex": _format_hex16(word(206)),
            "equalization_day_cycle_days": word(207),
            "equalization_time_hours": round(word(208) * 0.5, 1),
            "temperature_compensation_mv_per_c": _decode_signed16_setting(
                word(209)
            ),
            "max_charge_current_a": word(210),
            "max_discharge_current_a": word(211),
            "operating_basis": {
                "raw": operating_basis_code,
                "raw_hex": _format_hex16(operating_basis_code),
                "mode": {
                    0: "Voltage",
                    1: "Capacity",
                    2: "No battery",
                }.get(operating_basis_code),
            },
            "lithium_battery_wake": {
                "raw": lithium_wake_raw,
                "raw_hex": _format_hex16(lithium_wake_raw),
                "enabled": (
                    True
                    if lithium_wake_raw == 0
                    else False
                    if lithium_wake_raw == 1
                    else None
                ),
            },
            "battery_resistance_mohm": word(215),
            "charging_efficiency_percent": round(word(216) * 0.1, 1),
            "soc_thresholds_percent": {
                "shutdown": word(217),
                "restart": word(218),
                "low_battery": word(219),
            },
            "voltage_thresholds_v": {
                "shutdown": round(word(220) * 0.01, 2),
                "restart": round(word(221) * 0.01, 2),
                "low_battery": round(word(222) * 0.01, 2),
            },
        }

        result["generator_and_charging"] = {
            "maximum_generator_run_time_hours": round(word(223) * 0.1, 1),
            "generator_cooling_time_hours": round(word(224) * 0.1, 1),
            "generator_charge": {
                "start_voltage_v": round(word(225) * 0.01, 2),
                "start_soc_percent": word(226),
                "current_a": word(227),
                "enable_raw": word(231),
                "enable_raw_hex": _format_hex16(word(231)),
                "enabled": None,
            },
            "grid_charge": {
                "start_voltage_v": round(word(228) * 0.01, 2),
                "start_soc_percent": word(229),
                "current_a": word(230),
                "enable_raw": word(232),
                "enable_raw_hex": _format_hex16(word(232)),
                "enabled": None,
            },
        }

        result["generator_port_and_smart_load"] = {
            "solar_input": {
                "raw": solar_input_code,
                "raw_hex": _format_hex16(solar_input_code),
                "mode": {
                    0: "Solar",
                    1: "PSU",
                }.get(solar_input_code),
            },
            "force_generator_as_load": {
                "raw": force_generator_raw,
                "raw_hex": _format_hex16(force_generator_raw),
                "enabled": _decode_binary_setting(force_generator_raw),
            },
            "generator_port_mode": {
                "raw": generator_port_mode_code,
                "raw_hex": _format_hex16(generator_port_mode_code),
                "mode": {
                    0: "Generator input",
                    1: "Smart load output",
                    2: "Inverter input",
                }.get(generator_port_mode_code),
            },
            "smart_load": {
                "off_battery_voltage_v": round(word(236) * 0.01, 2),
                "off_battery_soc_percent": word(237),
                "on_battery_voltage_v": round(word(238) * 0.01, 2),
                "on_battery_soc_percent": word(239),
            },
            "pwm_test": {
                "raw": pwm_test_raw,
                "raw_hex": _format_hex16(pwm_test_raw),
                "enabled": _decode_binary_setting(pwm_test_raw),
            },
            "minimum_solar_power_to_start_generator_w": word(241),
            "gen_grid_signal_on_raw": word(242),
            "gen_grid_signal_on_raw_hex": _format_hex16(word(242)),
            "energy_management": {
                "raw": energy_management_code,
                "raw_hex": _format_hex16(energy_management_code),
                "mode": {
                    0: "Battery priority",
                    1: "Load first",
                }.get(energy_management_code),
            },
            "limit_control": {
                "raw": limit_control_code,
                "raw_hex": _format_hex16(limit_control_code),
                "mode": {
                    0: "Sell electricity",
                    1: "Built-in",
                    2: "External",
                }.get(limit_control_code),
            },
        }

        for address, reason in (
            (
                197,
                "No stable storage-settings semantic is assigned in V118; "
                "an older single-phase table labels it as a debug word"
            ),
            (
                198,
                "Not defined in the V118 storage-variable settings block"
            ),
            (
                199,
                "Not defined in the V118 storage-variable settings block"
            ),
            (
                206,
                "V118 names this ZeroExport power but does not document "
                "a unit or scale, so only the raw value is exposed"
            ),
            (
                212,
                "Reserved/undefined in V118"
            ),
            (
                231,
                "V118 names Generator charge enable but does not document "
                "the numeric encoding"
            ),
            (
                232,
                "V118 names Grid charge enable but does not document "
                "the numeric encoding"
            ),
            (
                242,
                "V118 names Gen_Grid_Signal On but does not document "
                "the numeric encoding"
            ),
        ):
            undecoded_raw[str(address)] = {
                "raw": word(address),
                "raw_hex": _format_hex16(word(address)),
                "reason": reason,
            }

    tou_word = word(248)

    day_bits = (
        ("monday", 1),
        ("tuesday", 2),
        ("wednesday", 3),
        ("thursday", 4),
        ("friday", 5),
        ("saturday", 6),
        ("sunday", 7),
    )

    tou_days = {}
    enabled_days = []

    for day_name, bit in day_bits:
        enabled = bool(tou_word & (1 << bit))
        tou_days[day_name] = enabled

        if enabled:
            enabled_days.append(day_name)

    slots = []

    for index in range(6):
        time_raw = word(250 + index)
        voltage_raw = word(262 + index)
        mode_raw = word(274 + index)

        slots.append({
            "slot": index + 1,
            "time_raw": time_raw,
            "time": _decode_hhmm_setting(time_raw),
            "power_w": word(256 + index),
            "battery_voltage_v": round(voltage_raw * 0.01, 2),
            "soc_percent": word(268 + index),
            "charge_mode_raw": mode_raw,
            "charge_mode_raw_hex": _format_hex16(mode_raw),
            "grid_charge_enabled": bool(mode_raw & 0x0001),
            "generator_charge_enabled": bool(mode_raw & 0x0002),
            "gm_mode": bool(mode_raw & 0x0004),
            "bu_mode": bool(mode_raw & 0x0008),
            "ch_mode": bool(mode_raw & 0x0010),
            "reserved_bits_raw": mode_raw & 0xFFE0,
            "reserved_bits_raw_hex": _format_hex16(mode_raw & 0xFFE0),
        })

    feature_word = word(280)
    micro_cutoff_code = feature_word & 0x000F
    gen_peak_code = (feature_word >> 4) & 0x000F
    grid_peak_code = (feature_word >> 8) & 0x000F

    arc_mode_code = word(283)
    grid_mode_code = word(284)
    grid_frequency_code = word(285)
    grid_type_code = word(286)

    result["maximum_grid_power_w"] = word(245)

    result["solar_sell"] = {
        "raw": word(247),
        "raw_hex": _format_hex16(word(247)),
        "enabled": _decode_binary_setting(word(247)),
    }

    result["time_of_use"] = {
        "raw": tou_word,
        "raw_hex": _format_hex16(tou_word),
        "enabled": bool(tou_word & 0x0001),
        "days": tou_days,
        "enabled_days": enabled_days,
        "work_mode_3": bool(tou_word & 0x0100),
        "reserved_bits_raw": tou_word & 0xFE00,
        "reserved_bits_raw_hex": _format_hex16(tou_word & 0xFE00),
        "slots": slots,
    }

    result["microinverter_and_peak_shaving"] = {
        "raw": feature_word,
        "raw_hex": _format_hex16(feature_word),

        "microinverter_export_cutoff_code": micro_cutoff_code,
        "microinverter_export_cutoff_enabled": _decode_nibble_enable(
            micro_cutoff_code
        ),

        "generator_peak_shaving_code": gen_peak_code,
        "generator_peak_shaving_enabled": _decode_nibble_enable(
            gen_peak_code
        ),

        "grid_peak_shaving_code": grid_peak_code,
        "grid_peak_shaving_enabled": _decode_nibble_enable(
            grid_peak_code
        ),

        "on_grid_always_on": bool(feature_word & 0x1000),
        "external_relay": bool(feature_word & 0x2000),
        "lithium_battery_lost_fault_enable": bool(
            feature_word & 0x4000
        ),
        "drm_enable": bool(feature_word & 0x8000),
    }

    result["grid"] = {
        "restore_connection_time_s": word(282),

        "solar_arc_fault_mode_code": arc_mode_code,
        "solar_arc_fault_mode": {
            0: "Disabled",
            1: "Enabled",
            2: "Reset request",
        }.get(arc_mode_code),

        "grid_mode_code": grid_mode_code,
        "grid_mode": {
            0: "General standard",
            1: "UL1741 & IEEE1547",
            2: "CPUC RULE21",
            3: "SRD-UL1741",
        }.get(grid_mode_code),

        "grid_frequency_code": grid_frequency_code,
        "grid_frequency_hz": {
            0: 50,
            1: 60,
        }.get(grid_frequency_code),

        "grid_type_code": grid_type_code,
        "grid_type": {
            0: "Single-phase 220/230/240V",
            1: "Two-phase 120/240V",
            2: "Three-phase 208V / 120-degree 120V",
            3: "120V single-phase",
        }.get(grid_type_code),

        "voltage_high_v": round(word(287) * 0.1, 1),
        "voltage_low_v": round(word(288) * 0.1, 1),
        "frequency_high_hz": round(word(289) * 0.01, 2),
        "frequency_low_hz": round(word(290) * 0.01, 2),

        "generator_connected_to_grid_input_raw": word(291),
        "generator_connected_to_grid_input": _decode_binary_setting(
            word(291)
        ),

        "generator_peak_shaving_power_w": word(292),
        "grid_peak_shaving_power_w": word(293),
        "smart_load_open_delay_min": word(294),
        "output_pf_setting_percent": round(word(295) * 0.1, 1),

        "external_relay_raw": word(296),
        "external_relay_raw_hex": _format_hex16(word(296)),
        "external_relay_active_bits": [
            bit
            for bit in range(9)
            if word(296) & (1 << bit)
        ],
    }

    for address, reason in (
        (
            246,
            "External current sensor clamp field is "
            "variant-specific/unclear in the available table"
        ),
        (
            249,
            "Reserved/undefined in V118"
        ),
        (
            281,
            "Hardware capture conflicts with documented 0/1 range; "
            "semantic decoding intentionally disabled"
        ),
    ):
        undecoded_raw[str(address)] = {
            "raw": word(address),
            "raw_hex": _format_hex16(word(address)),
            "reason": reason,
        }

    result["undecoded_raw"] = undecoded_raw

    if extended_values is not None:
        result["grid_support_configuration"] = decode_extended_settings(
            extended_values
        )

    return result


def read_settings(config, str_to_bool):
    """Read validated single-phase settings through Modbus function 0x03.

    Primary settings remain one request for 197..296.
    Extended grid-support settings are a second request for 326..416.

    If the optional extended read fails, the already validated v2 settings are
    still returned and the extended section is marked unavailable.
    """
    values = read_raw_registers(
        config,
        str_to_bool,
        197,
        100
    )

    if values is None:
        return None

    extended_values = read_raw_registers(
        config,
        str_to_bool,
        326,
        91
    )

    result = decode_settings(
        values,
        extended_values=extended_values
    )

    if extended_values is None:
        result["grid_support_configuration"] = {
            "available": False,
            "register_range": {
                "start": 326,
                "end": 416,
                "count": 91,
            },
            "reason": "extended read failed after configured retries",
        }

    return result




def _decode_int32_low_high(low_word, high_word):
    """Decode a signed 32-bit Modbus value with low word first."""
    return _decode_register_value(
        [
            int(low_word) & 0xFFFF,
            int(high_word) & 0xFFFF,
        ],
        "int32",
        2
    )


def _decode_uint32_low_high(low_word, high_word):
    """Decode an unsigned 32-bit Modbus value with low word first."""
    return _decode_register_value(
        [
            int(low_word) & 0xFFFF,
            int(high_word) & 0xFFFF,
        ],
        "uint32",
        2
    )



def _build_raw_register_item(address, value):
    """Build one stable raw register item for revision-sensitive data."""
    unsigned = int(value) & 0xFFFF

    return {
        "address": int(address),
        "raw": unsigned,
        "raw_hex": _format_hex16(unsigned),
        "int16": (
            unsigned - 0x10000
            if unsigned & 0x8000
            else unsigned
        ),
        "zero": unsigned == 0,
    }


def _build_zero_nonzero_runs(items):
    """Group adjacent raw-register items by zero/non-zero state."""
    runs = []

    for item in items:
        state = "zero" if item["zero"] else "nonzero"

        if (
                not runs
                or runs[-1]["state"] != state
                or runs[-1]["end"] + 1 != item["address"]):
            runs.append({
                "start": item["address"],
                "end": item["address"],
                "state": state,
                "count": 1,
            })
        else:
            runs[-1]["end"] = item["address"]
            runs[-1]["count"] += 1

    return runs



def decode_system_status(values):
    """Decode system/status registers 417..499 conservatively.

    Registers 417..437 preserve the validated system-v1 behavior.

    Registers 438..499 are exposed as revision-sensitive raw-only data.
    No semantic mapping is assigned because the validated 5 kW inverter
    does not follow the available V118 interpretation consistently in this
    region.

    This keeps the data observable for cross-device comparison without
    inventing names, units, scales or bit meanings.
    """
    if values is None or len(values) < 83:
        raise ValueError(
            "system status requires registers 417 through 499"
        )

    raw = [int(value) & 0xFFFF for value in values[:83]]

    def word(address):
        return raw[address - 417]

    parallel_1 = word(417)
    parallel_2 = word(418)

    parallel_enabled = bool(parallel_1 & 0x0001)
    master_bit = bool(parallel_1 & 0x0002)
    phase_code = (parallel_1 >> 8) & 0x0003
    modbus_sn = (parallel_1 >> 10) & 0x003F

    phase_map = {
        0: "A",
        1: "B",
        2: "C",
        3: None,
    }

    lithium_low = word(419)
    lithium_high = word(420)

    time_words = [word(421), word(422), word(423)]
    time_bytes = []

    for register_address, value in zip(
            (421, 422, 423),
            time_words):
        time_bytes.append({
            "register": register_address,
            "raw": value,
            "raw_hex": _format_hex16(value),
            "high_byte": (value >> 8) & 0xFF,
            "low_byte": value & 0xFF,
        })

    meter_pairs = (
        ("total", 424, 425),
        ("phase_a", 426, 427),
        ("phase_b", 428, 429),
        ("phase_c", 430, 431),
    )

    meter_power = {}

    for name, low_address, high_address in meter_pairs:
        low = word(low_address)
        high = word(high_address)

        meter_power[name] = {
            "low_word_raw": low,
            "low_word_hex": _format_hex16(low),
            "high_word_raw": high,
            "high_word_hex": _format_hex16(high),
            "signed_int32_w": _decode_int32_low_high(low, high),
        }

    energy_raw = []

    energy_reasons = {
        432: "V118 labels this as daily grid-sell energy; hardware semantics not validated",
        433: "V118 labels this as total grid-sell energy low word; hardware semantics not validated",
        434: "V118 labels this as total grid-sell energy high word; hardware semantics not validated",
        435: "V118 labels this as daily grid-buy energy; hardware semantics not validated",
        436: "V118 labels this as total grid-buy energy low word; hardware semantics not validated",
        437: "V118 labels this as total grid-buy energy high word; hardware semantics not validated",
    }

    for address in range(432, 438):
        value = word(address)
        energy_raw.append({
            "address": address,
            "raw": value,
            "raw_hex": _format_hex16(value),
            "int16": (
                value - 0x10000
                if value & 0x8000
                else value
            ),
            "reason": energy_reasons[address],
        })

    return {
        "read_only": True,
        "register_range": {
            "start": 417,
            "end": 499,
            "count": 83,
        },

        "parallel": {
            "register_1_raw": parallel_1,
            "register_1_raw_hex": _format_hex16(parallel_1),
            "parallel_enabled": parallel_enabled,
            "master_bit": master_bit,
            "role_if_parallel_enabled": (
                "master"
                if parallel_enabled and master_bit
                else "slave"
                if parallel_enabled
                else None
            ),
            "phase_code": phase_code,
            "phase_if_parallel_enabled": (
                phase_map.get(phase_code)
                if parallel_enabled
                else None
            ),
            "modbus_sn": modbus_sn,

            "register_2_raw": parallel_2,
            "register_2_raw_hex": _format_hex16(parallel_2),
            "a_phase_inverter_count": parallel_2 & 0x001F,
            "b_phase_inverter_count": (parallel_2 >> 5) & 0x001F,
            "c_phase_inverter_count": (parallel_2 >> 10) & 0x001F,
            "reserved_bit_15": bool(parallel_2 & 0x8000),
        },

        "lithium_battery_version": {
            "low_word_raw": lithium_low,
            "low_word_hex": _format_hex16(lithium_low),
            "high_word_raw": lithium_high,
            "high_word_hex": _format_hex16(lithium_high),
            "uint32_low_word_first": _decode_uint32_low_high(
                lithium_low,
                lithium_high
            ),
            "note": (
                "V118 documents low/high version words but does not define "
                "a printable version-string format"
            ),
        },

        "system_time_raw": {
            "registers": time_bytes,
            "decoded": None,
            "reason": (
                "Current 5 kW hardware capture reports zero in 421..423; "
                "byte order/calendar interpretation is not hardware-validated"
            ),
        },

        "meter_active_power": {
            "unit": "W",
            "word_order": "low_word_first",
            "total_sign_convention": (
                "V118: grid buy is negative, grid sell is positive"
            ),
            "values": meter_power,
            "validation": (
                "documented; current hardware capture is zero for 424..431"
            ),
        },

        "meter_energy_raw_432_437": {
            "decoded": False,
            "reason": (
                "V118 documents grid buy/sell energy counters here, but the "
                "validated 5 kW capture does not establish those semantics. "
                "Raw values are preserved without applying energy scales."
            ),
            "registers": energy_raw,
        },

        "revision_sensitive_raw_438_499": (
            lambda items: {
                "decoded": False,
                "register_range": {
                    "start": 438,
                    "end": 499,
                    "count": 62,
                },
                "reason": (
                    "No stable semantic mapping is assigned for the validated "
                    "5 kW firmware. Values are intentionally exposed only as "
                    "raw/hex/int16 for future cross-model and firmware "
                    "comparison."
                ),
                "zero_count": sum(
                    1
                    for item in items
                    if item["zero"]
                ),
                "nonzero_count": sum(
                    1
                    for item in items
                    if not item["zero"]
                ),
                "runs": _build_zero_nonzero_runs(items),
                "registers": items,
                "validation_note": (
                    "The validated 5 kW inventory showed structured values in "
                    "this region, including an exact raw-value repetition at "
                    "488..499 of the previously observed 331..342 sequence. "
                    "That observation is not treated as a protocol semantic "
                    "or mirror guarantee."
                ),
            }
        )([
            _build_raw_register_item(
                address,
                word(address)
            )
            for address in range(438, 500)
        ]),
    }


def read_system_status(config, str_to_bool):
    """Read system/status registers 417..499 via one Modbus 0x03 request."""
    values = read_raw_registers(
        config,
        str_to_bool,
        417,
        83
    )

    if values is None:
        return None

    return decode_system_status(values)



def _format_hex16(value):
    """Return one 16-bit value as uppercase hexadecimal text."""
    return "0x{:04X}".format(int(value) & 0xFFFF)


def _decode_ascii_words(words):
    """Decode Modbus words containing two big-endian ASCII bytes each."""
    data = bytearray()

    for word in words:
        word = int(word) & 0xFFFF
        data.append((word >> 8) & 0xFF)
        data.append(word & 0xFF)

    return bytes(data).rstrip(b"\x00").decode("ascii", errors="replace")


def _decode_device_type(raw_value):
    """Decode the protocol device-family field without hiding byte layout.

    The V118 table lists family values as 0x0200, 0x0300, 0x0400 and 0x0500.
    The tested SUN storage firmware returns 0x0003. Accept both representations
    while preserving the exact raw code separately in device_info output.
    """
    raw_value = int(raw_value) & 0xFFFF

    labels = {
        2: "String inverter",
        3: "Single-phase storage inverter",
        4: "Microinverter",
        5: "Three-phase storage inverter",
    }

    if raw_value in (0x0200, 0x0300, 0x0400, 0x0500):
        family = (raw_value >> 8) & 0xFF
        return labels.get(family)

    if raw_value in (2, 3, 4, 5):
        return labels.get(raw_value)

    return None


def _decode_protocol_version(raw_value):
    """Decode communication protocol version as high-byte.low-byte."""
    raw_value = int(raw_value) & 0xFFFF
    return "{}.{}".format(
        (raw_value >> 8) & 0xFF,
        raw_value & 0xFF
    )


def decode_device_info(values):
    """Decode intrinsic device information registers 0..19.

    Only fields whose encoding is defined by the available Deye V118 protocol
    are converted. Firmware version registers are intentionally exposed as raw
    hexadecimal values because the document identifies the fields but does not
    define their internal version-number encoding.
    """
    if values is None or len(values) < 20:
        raise ValueError("device info requires registers 0 through 19")

    device_type_raw = values[0]
    protocol_raw = values[2]
    mppt_phases_raw = int(values[18]) & 0xFFFF

    rated_power_raw = (
        ((int(values[17]) & 0xFFFF) << 16)
        | (int(values[16]) & 0xFFFF)
    )

    chip_code = int(values[9]) & 0x000F
    chip_labels = {
        1: "AT32F403A_DEVICE",
        2: "SXX32F103_DEVICE",
        3: "GD32F103_DEVICE",
        4: "GD32F303_DEVICE",
    }

    grid_voltage_code = int(values[19]) & 0xFFFF
    grid_voltage_profiles = {
        0: "127/220V",
        1: "220/380V",
    }

    return {
        "device_type_code": _format_hex16(device_type_raw),
        "device_type": _decode_device_type(device_type_raw),
        "modbus_address": int(values[1]) & 0xFFFF,
        "protocol_version_raw": _format_hex16(protocol_raw),
        "protocol_version": _decode_protocol_version(protocol_raw),
        "serial_number": _decode_ascii_words(values[3:8]),
        "chip_type_raw": _format_hex16(values[9]),
        "chip_type_code": chip_code,
        "chip_type": chip_labels.get(chip_code),
        "control_board_aux_version_raw": _format_hex16(values[11]),
        "control_board_firmware_raw": _format_hex16(values[13]),
        "communication_board_firmware_raw": _format_hex16(values[14]),
        "rated_power_w": round(rated_power_raw * 0.1, 1),
        "mppt_phase_raw": _format_hex16(mppt_phases_raw),
        "mppt_count": (mppt_phases_raw >> 8) & 0xFF,
        "phase_count": mppt_phases_raw & 0xFF,
        "rated_grid_voltage_code": grid_voltage_code,
        "rated_grid_voltage_profile": grid_voltage_profiles.get(
            grid_voltage_code
        ),
    }


def read_device_info(config, str_to_bool):
    """Read and decode static inverter information registers 0..19."""
    values = read_raw_registers(
        config,
        str_to_bool,
        0,
        20
    )

    if values is None:
        return None

    return decode_device_info(values)


def decode_battery_info(values):
    """Decode Deye lithium-battery registers 312..325.

    The available V118 protocol defines units for 312..321. Hardware
    validation established signed int16 encoding for register 318.

    Register 322 is preserved as an alarm raw word because the available table
    does not define its individual alarm bits.

    For register 324 only the documented Bit0 and Bit1 flags are decoded.
    Other bits remain visible through the raw word instead of being guessed.

    Register 325 is mapped only for protocol codes explicitly documented in
    the available table; unknown values remain visible as the numeric code.
    """
    if values is None or len(values) < 14:
        raise ValueError("battery info requires registers 312 through 325")

    raw = [int(value) & 0xFFFF for value in values[:14]]

    return {
        "charging_voltage_v": round(raw[0] * 0.01, 2),
        "discharge_voltage_v": round(raw[1] * 0.01, 2),
        "charging_current_limit_a": raw[2],
        "discharge_current_limit_a": raw[3],
        "capacity_percent": raw[4],
        "realtime_voltage_v": round(raw[5] * 0.01, 2),

        # Register 318 is documented as real-time current with 1 A resolution.
        # Hardware validation on the 5 kW single-phase storage inverter showed two's-complement
        # values 0x0000 -> 0 A and 0xFFFF -> -1 A while register 191 reported
        # small negative battery current. Decode it as signed int16 while
        # preserving the original raw word for diagnostics.
        "realtime_current_a": (
            raw[6] - 0x10000 if raw[6] & 0x8000 else raw[6]
        ),
        "realtime_current_raw": raw[6],
        "realtime_current_raw_hex": _format_hex16(raw[6]),

        "realtime_temperature_c": round(raw[7] * 0.1 - 100.0, 1),
        "maximum_charge_current_limit_a": raw[8],
        "maximum_discharge_current_limit_a": raw[9],

        # The table names register 322 as "Lithium battery alarm" but does not
        # define the alarm bit map. Preserve it instead of inventing labels.
        "alarm_raw": raw[10],
        "alarm_raw_hex": _format_hex16(raw[10]),
        "alarm_nonzero": raw[10] != 0,

        # Register 323: lithium battery fault location.
        # The available table names the word but does not provide a detailed
        # location/value map, so preserve it as raw data.
        "fault_location_raw": raw[11],
        "fault_location_raw_hex": _format_hex16(raw[11]),
        "fault_location_nonzero": raw[11] != 0,

        # Register 324: lithium battery symbol 2.
        # Only Bit0 and Bit1 are explicitly described by the available table.
        "symbol2_raw": raw[12],
        "symbol2_raw_hex": _format_hex16(raw[12]),
        "vacancy_flag": bool(raw[12] & 0x0001),
        "strong_impact_flag": bool(raw[12] & 0x0002),

        # Register 325: lithium battery type/protocol.
        "battery_type_code": raw[13],
        "battery_type_raw_hex": _format_hex16(raw[13]),
        "battery_type": {
            0x0000: "PYLON/SOLAX/common CAN",
            0x0001: "Tianbangda RS485 Modbus",
            0x0002: "KOK",
        }.get(raw[13]),
    }


def read_battery_info(config, str_to_bool):
    """Read and decode Deye lithium-battery information registers 312..325."""
    values = read_raw_registers(
        config,
        str_to_bool,
        312,
        14
    )

    if values is None:
        return None

    return decode_battery_info(values)


def _snapshot_section_result(data=None, error=None, warnings=None):
    """Return one transport-neutral snapshot section result."""
    return {
        "data": data,
        "error": error,
        "warnings": list(warnings or []),
    }


def _snapshot_all_error_results(message):
    """Build all-section error results for a serial-open failure."""
    return {
        name: _snapshot_section_result(
            data=None,
            error=message
        )
        for name in (
            "device_info",
            "telemetry",
            "battery",
            "settings",
            "system",
        )
    }


def _snapshot_try_decode(reader, error_message):
    """Run one shared-session read/decode step without aborting the snapshot."""
    try:
        data = reader()
    except Exception as exc:
        return _snapshot_section_result(
            data=None,
            error=str(exc)
        )

    if data is None:
        return _snapshot_section_result(
            data=None,
            error=error_message
        )

    return _snapshot_section_result(data=data)


def read_snapshot_sections_shared(
        config,
        str_to_bool,
        registers_file):
    """Read all snapshot sections through one exclusive serial session.

    Healthy-path Modbus 0x03 request plan:
      0..19
      telemetry blocks 59..95, 100..116, 150..196
      197..321
      322..416
      417..499

    That is one serial open and seven requests on the validated configuration.

    The settings/BMS region is coalesced only at transport level. Existing
    decode_settings() and decode_battery_info() receive exact validated slices.
    """
    import serial

    port = config.get("PORT")
    if port is None:
        return _snapshot_all_error_results(
            "PORT parameter missing in config"
        )

    baudrate = int(config.get("BAUDRATE", 9600))
    debug = str_to_bool(config.get("DEBUG", "false"))

    if debug:
        print(
            "Opening shared snapshot serial session on {}".format(
                port
            )
        )

    try:
        ser = serial.Serial(
            port,
            baudrate,
            timeout=0.5,
            exclusive=True
        )
    except Exception as exc:
        return _snapshot_all_error_results(
            "Error opening port: {}".format(exc)
        )

    results = {
        "device_info": _snapshot_section_result(),
        "telemetry": _snapshot_section_result(),
        "battery": _snapshot_section_result(),
        "settings": _snapshot_section_result(),
        "system": _snapshot_section_result(),
    }

    try:
        # Device info.
        try:
            info_values = _read_raw_registers_from_serial(
                ser,
                config,
                str_to_bool,
                0,
                20,
                name="Snapshot device info 0-19"
            )

            if info_values is None:
                results["device_info"] = _snapshot_section_result(
                    data=None,
                    error=(
                        "device info read failed after configured retries"
                    )
                )
            else:
                results["device_info"] = _snapshot_section_result(
                    data=decode_device_info(info_values)
                )
        except Exception as exc:
            results["device_info"] = _snapshot_section_result(
                data=None,
                error=str(exc)
            )

        # Telemetry, using exactly the same core as the public read command.
        try:
            telemetry = _read_deye_data_from_serial(
                ser,
                config,
                str_to_bool,
                registers_file
            )
            results["telemetry"] = _snapshot_section_result(
                data=telemetry
            )
        except Exception as exc:
            results["telemetry"] = _snapshot_section_result(
                data=None,
                error=str(exc)
            )

        # Coalesced settings + BMS.
        config_warnings = []

        block_a = _read_raw_registers_from_serial(
            ser,
            config,
            str_to_bool,
            197,
            125,
            name="Snapshot settings/BMS 197-321"
        )

        if block_a is not None:
            base_settings_values = block_a[0:100]
            battery_head = block_a[115:125]
        else:
            config_warnings.append(
                "coalesced block 197-321 failed; used validated fallback ranges"
            )

            base_settings_values = _read_raw_registers_from_serial(
                ser,
                config,
                str_to_bool,
                197,
                100,
                name="Snapshot fallback settings 197-296"
            )

            battery_head = _read_raw_registers_from_serial(
                ser,
                config,
                str_to_bool,
                312,
                10,
                name="Snapshot fallback BMS 312-321"
            )

        block_b = _read_raw_registers_from_serial(
            ser,
            config,
            str_to_bool,
            322,
            95,
            name="Snapshot BMS/settings 322-416"
        )

        if block_b is not None:
            battery_tail = block_b[0:4]
            extended_settings_values = block_b[4:95]
        else:
            config_warnings.append(
                "coalesced block 322-416 failed; used validated fallback ranges"
            )

            battery_tail = _read_raw_registers_from_serial(
                ser,
                config,
                str_to_bool,
                322,
                4,
                name="Snapshot fallback BMS 322-325"
            )

            extended_settings_values = _read_raw_registers_from_serial(
                ser,
                config,
                str_to_bool,
                326,
                91,
                name="Snapshot fallback settings 326-416"
            )

        # Battery.
        if battery_head is not None and battery_tail is not None:
            try:
                results["battery"] = _snapshot_section_result(
                    data=decode_battery_info(
                        list(battery_head) + list(battery_tail)
                    ),
                    warnings=config_warnings
                )
            except Exception as exc:
                results["battery"] = _snapshot_section_result(
                    data=None,
                    error=str(exc),
                    warnings=config_warnings
                )
        else:
            results["battery"] = _snapshot_section_result(
                data=None,
                error=(
                    "battery information read failed after configured retries"
                ),
                warnings=config_warnings
            )

        # Settings.
        if base_settings_values is None:
            results["settings"] = _snapshot_section_result(
                data=None,
                error="settings read failed after configured retries",
                warnings=config_warnings
            )
        else:
            try:
                settings_data = decode_settings(
                    base_settings_values,
                    extended_values=extended_settings_values
                )

                if extended_settings_values is None:
                    settings_data["grid_support_configuration"] = {
                        "available": False,
                        "register_range": {
                            "start": 326,
                            "end": 416,
                            "count": 91,
                        },
                        "reason": (
                            "extended read failed after configured retries"
                        ),
                    }

                results["settings"] = _snapshot_section_result(
                    data=settings_data,
                    warnings=config_warnings
                )

            except Exception as exc:
                results["settings"] = _snapshot_section_result(
                    data=None,
                    error=str(exc),
                    warnings=config_warnings
                )

        # System.
        try:
            system_values = _read_raw_registers_from_serial(
                ser,
                config,
                str_to_bool,
                417,
                83,
                name="Snapshot system 417-499"
            )

            if system_values is None:
                results["system"] = _snapshot_section_result(
                    data=None,
                    error=(
                        "system status read failed after configured retries"
                    )
                )
            else:
                results["system"] = _snapshot_section_result(
                    data=decode_system_status(system_values)
                )

        except Exception as exc:
            results["system"] = _snapshot_section_result(
                data=None,
                error=str(exc)
            )

        return results

    finally:
        ser.close()

