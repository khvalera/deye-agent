# Deye Agent

[English](README.md) | [Українська](README_UK.md)


`deye-agent` is a Python 3.6 compatible monitoring agent for Deye inverters
connected over RS485/Modbus RTU. It provides CLI diagnostics, normalized
metrics, MQTT publishing, a cached HTTP API and a read-only web dashboard.

The current production path is intentionally conservative: normal monitoring
uses validated read-only registers and does not expose inverter write controls.

## Release 0.2.0 highlights

- Reliable RS485 reads with retries and strict Modbus response validation.
- Process-wide inverter-access lock to prevent concurrent local consumers.
- Protocol profiles with a hardware-validated `single_phase_storage` profile.
- Read-only device, battery/BMS, settings, system-status and snapshot commands.
- Stable normalized metrics schema with **89 metric IDs**.
- Stable MQTT metric topics in addition to the legacy MQTT payload.
- Cached HTTP API that does not trigger browser-originated RS485 reads.
- Responsive web dashboard with live overview and RAM-only history charts.
- Web UI translations: English, Ukrainian, Polish and German.
- Mandatory login/password protection whenever the HTTP API is enabled.
- PBKDF2-SHA256 password hashing and RAM-only authenticated sessions.
- Fixed numeric formatting for voltage, current and frequency values.

See [CHANGELOG.md](CHANGELOG.md) and
[docs/RELEASE_0.2.0.md](docs/RELEASE_0.2.0.md) for details.

## Hardware/profile status

### `single_phase_storage`

Status: **hardware-validated**.

The current validation work was performed on a **5 kW single-phase storage
inverter**. The exact model identifier of that unit has not been recorded, so
the profile is deliberately named by inverter family rather than by one exact
model.

### `three_phase_storage`

Status: **reference-only**.

The three-phase map is kept separate because register meanings differ between
single-phase and three-phase families. It is not enabled for normal runtime
polling until separate hardware validation is completed.

## Requirements

- Python **3.6+**.
- Linux.
- RS485 access to the inverter.
- `pyserial`, `PyYAML`, `paho-mqtt`, `chardet`, `idna`.

The current ClearOS production environment uses Python 3.6.8.

## Installation

```bash
git clone https://github.com/khvalera/deye-agent.git
cd deye-agent
python3 setup.py install
```

Review the example configuration under:

```text
data/etc/deye-agent/
```

The validated runtime profile should normally be installed as:

```text
/etc/deye-agent/profiles/single_phase_storage.yaml
```

## Basic usage

List protocol profiles:

```bash
deye-agent profiles
```

Read current telemetry:

```bash
deye-agent --profile single_phase_storage read
```

Read a complete read-only snapshot:

```bash
deye-agent --profile single_phase_storage snapshot --json
```

Read normalized metrics:

```bash
deye-agent --profile single_phase_storage metrics --json
```

Start the monitoring loop:

```bash
deye-agent \
  --config /etc/deye-agent/deye-agent.conf \
  --profile single_phase_storage \
  run
```

Additional diagnostic/read-only commands include:

```text
raw-read
info
battery
settings
system
snapshot
metrics
publish-metrics
inventory
profiles
```

## Stable metrics and MQTT

Release 0.2.0 exposes **89 stable metric IDs** under the
`deye-agent.metrics.v1` schema.

When both switches are enabled:

```text
MQTT_ENABLED=true
MQTT_METRICS_ENABLED=true
```

stable metrics are published under:

```text
<MQTT_TOPIC>/metrics/<stable.metric.id>
```

The legacy MQTT output remains available.

The MQTT client uses MQTT 3.1.1, bounded connection/publish waits and explicit
publication completion tracking.

## HTTP API and dashboard

The HTTP layer reads only the runtime cache. Opening or refreshing the browser
does **not** create additional Modbus requests.

Enable it with:

```text
HTTP_API_ENABLED=true
HTTP_API_HOST=0.0.0.0
HTTP_API_PORT=8765
```

The API endpoints are:

```text
GET /api/v1/health
GET /api/v1/overview
GET /api/v1/history?minutes=60
GET /api/v1/metrics
GET /api/v1/snapshot
```

### Authentication

Authentication is mandatory whenever `HTTP_API_ENABLED=true`.

Generate a password hash interactively:

```bash
deye-agent auth-hash
```

Then configure:

```text
HTTP_AUTH_USERNAME=admin
HTTP_AUTH_PASSWORD_HASH=pbkdf2_sha256$...
HTTP_AUTH_SESSION_SECONDS=43200
HTTP_AUTH_COOKIE_SECURE=false
```

If the username or password hash is missing, the HTTP API fails closed instead
of exposing an anonymous dashboard.

Without a valid browser session:

```text
GET /           -> redirect to /login
GET /api/v1/*   -> HTTP 401
```

Passwords are verified using PBKDF2-HMAC-SHA256 with a random salt. Browser
sessions use random server-side tokens stored only in RAM. Session cookies are
`HttpOnly` and `SameSite=Strict`.

`HTTP_AUTH_COOKIE_SECURE=true` should only be used when the browser reaches the
service over HTTPS.

> Direct plain HTTP does not encrypt the login credentials on the network.
> Use HTTPS or a trusted isolated network when confidentiality is required.

## Dashboard

The dashboard is dependency-free and reads `/api/v1/overview` plus the history
endpoint. It includes:

- Grid input power, voltage, current and frequency.
- Explicit grid connection status.
- Load power, inverter output voltage, load current and load frequency.
- Battery state of charge, voltage, current, power and BMS information.
- PV values.
- Daily energy totals.
- Operating status and configuration summary.
- Historical charts for power, battery SOC, grid input voltage, battery voltage
  and inverter output voltage.

Numeric formatting is stable in the UI, for example:

```text
234.0 V
6.50 A
50.00 Hz
```

rather than changing width when trailing zeroes are present.

Supported web languages:

```text
English
Українська
Polski
Deutsch
```

## RAM history

History is intentionally memory-only in this release:

```text
HTTP_HISTORY_ENABLED=true
HTTP_HISTORY_MAX_SAMPLES=720
HTTP_HISTORY_RETENTION_SECONDS=21600
```

It is reset when the agent process starts again. Persistent on-disk history is
not part of release 0.2.0.

## Read-only register coverage

The release includes validated read-only mappings for:

- Device information.
- Energy/statistics.
- PV/DC data.
- Real-time grid/inverter/load/battery telemetry.
- Warnings/fault status.
- Battery/BMS summary.
- Selected inverter settings.
- Selected system/status values.

Two notable values added during current hardware validation are:

```text
Register 79  -> Grid input frequency, scale 0.01 Hz
Register 150 -> Grid input voltage, scale 0.1 V
Register 154 -> Inverter output voltage, scale 0.1 V
```

Reserved or revision-sensitive registers are not assigned semantics without
validation.

## RS485 reliability

The read path includes:

- Exclusive serial-open mode when supported.
- Configurable retry attempts.
- Retry delay.
- Exact response length validation.
- Slave-ID validation.
- Function-code validation.
- Byte-count validation.
- CRC validation.
- A process-wide Linux abstract UNIX-socket lock around inverter access.

Normal telemetry keeps the existing open/read/close cycle. The combined
snapshot uses one shared serial session for its coalesced read blocks.

## Alarm confirmation

Alarm notifications can require consecutive valid abnormal samples:

```text
ALARM_CONFIRMATIONS=2
```

A failed/absent read does not count as a confirmation.

## License

Apache License 2.0.
