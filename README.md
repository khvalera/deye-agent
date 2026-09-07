# Deye Agent

[English](README.md) | [Українська](README_UK.md)

`deye-agent` is a Python 3.6 compatible monitoring agent for Deye inverters
connected over RS485/Modbus RTU. It provides CLI diagnostics, normalized
metrics, MQTT publishing, threshold notifications, a cached HTTP API and a
read-only web dashboard.

The production path is intentionally conservative: normal monitoring uses
validated read-only registers and does not expose inverter write controls.

## Release 0.2.1 highlights

Release 0.2.1 keeps the read-only acquisition and API architecture from 0.2.0
and adds configurable alarm rules and local Webconfig-friendly telemetry.

- Added standalone `/etc/deye-agent/alarms.yaml` rules, independent from the
  Modbus register/profile map.
- Added `le` and `ge` threshold operators with explicit hysteresis through
  separate alarm and clear thresholds.
- Added custom alarm/clear messages with safe literal placeholders.
- Added alarm delivery through Email, Matrix and MQTT.
- Added stable MQTT alarm documents using schema `deye-agent.alarm.v1`.
- Added boolean threshold support for aggregate `Has Warning` and `Has Fault`
  metrics.
- Added hot reload of `alarms.yaml`; editing the rules does not require a
  daemon restart.
- Added `/run/deye-agent/telemetry.json`, written from telemetry already read by
  the daemon. Local UI consumers can read it without initiating extra RS485
  traffic.
- Removed legacy alarm/cancel fields from the protocol profile; threshold policy
  now lives only in `alarms.yaml`.
- Added source/RPM build scripts and a release validation script.
- Updated the RPM spec so backend configuration, profiles, alarms and the
  systemd unit are owned by the `deye-agent` package.
- Removed tracked Python bytecode/cache artifacts from the release tree.

The bundled alarm thresholds are examples for the currently validated profile.
Review them for the exact inverter, battery, grid requirements and installation
before enabling notification channels.

For the full release notes, see [CHANGELOG.md](CHANGELOG.md) and
[docs/RELEASE_0.2.1.md](docs/RELEASE_0.2.1.md).

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

Source installation of the Python package:

```bash
git clone https://github.com/khvalera/deye-agent.git
cd deye-agent
python3 setup.py install
```

Example backend configuration is stored under:

```text
data/etc/deye-agent/
```

The validated runtime profile should normally be installed as:

```text
/etc/deye-agent/profiles/single_phase_storage.yaml
```

The threshold-rule file is:

```text
/etc/deye-agent/alarms.yaml
```

The RPM packaging path installs the backend configuration, profiles, alarm
rules and systemd service as package-owned files. Configuration files are
installed with `noreplace` semantics so package upgrades do not silently
replace local configuration.

## Building release artifacts

Run the release checks first:

```bash
./packaging/release_check.sh
```

Create a GitHub/source-style tarball from the current Git ref:

```bash
./packaging/build_source.sh
```

The default output is:

```text
dist/deye-agent-0.2.1.tar.gz
```

Build source and binary RPMs on a system with `rpmbuild`:

```bash
./packaging/build_rpm.sh
```

The RPM build uses an isolated tree under `dist/rpmbuild/` and does not modify
system RPM build directories.

## RS485 connection examples

The repository keeps the original connection photos and diagrams. They are
useful when wiring the inverter to a USB-RS485 or RS485-UART-TTL adapter.

### RS485-UART-TTL

[![RS485-UART-TTL connection](data/images/RS485–UART-TTL.JPG)](data/images/RS485–UART-TTL.JPG)

### USB-RS485

[![USB-RS485 connection 1](data/images/USB-RS485-1.png)](data/images/USB-RS485-1.png)

[![USB-RS485 connection 2](data/images/USB-RS485-2.JPG)](data/images/USB-RS485-2.JPG)

> RS485 pinouts can differ between inverter families. Verify the connector
> pinout for the exact inverter before wiring.

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

## Alarm rules

Alarm policy is stored separately from the hardware register map:

```text
ALARMS_FILE=/etc/deye-agent/alarms.yaml
ALARM_CONFIRMATIONS=2
```

`alarms.yaml` schema version 1 supports these operators:

```text
le  alarm when value <= alarm; clear when value >= cancel
ge  alarm when value >= alarm; clear when value <= cancel
```

For `le`, `cancel` must be greater than `alarm`. For `ge`, `cancel` must be
lower than `alarm`. This creates explicit hysteresis and avoids rapid
alarm/clear oscillation around one threshold.

Example rule:

```yaml
battery_temperature_low:
  enabled: true
  metric: Battery Temperature
  operator: le
  alarm: 5
  cancel: 10
  message: "Battery temperature dropped to {value} C."
  clear_message: "Battery temperature recovered to {value} C."
```

Supported message placeholders are:

```text
{name} {value} {unit} {alarm} {cancel} {profile}
```

The file is monitored for changes and valid edits are loaded without restarting
the daemon. If the file is invalid, threshold notifications fail closed while
the main monitoring loop can continue.

The bundled rules cover inverter fault/warning state, low/high grid voltage,
low/high grid frequency, low battery capacity, low/high battery temperature,
high IGBT temperature and high load power.

### Alarm notification channels

Email and Matrix continue to use their existing global enable switches:

```text
NOTIFY_EMAIL_ENABLED=false
NOTIFY_MATRIX_ENABLED=false
```

MQTT alarm events reuse the existing broker settings:

```text
NOTIFY_MQTT_ENABLED=false
NOTIFY_MQTT_TOPIC=solar/deye/alarms
```

If `NOTIFY_MQTT_TOPIC` is empty, the destination defaults to
`<MQTT_TOPIC>/alarms`.

MQTT alarm messages use the stable JSON schema:

```text
deye-agent.alarm.v1
```

with event type `alarm` or `clear`, rule ID, metric name, current value, unit,
operator, alarm/clear thresholds, profile and rendered message.

## Local telemetry cache

The running daemon writes its already-acquired telemetry to:

```text
/run/deye-agent/telemetry.json
```

The cache uses schema:

```text
deye-agent.telemetry-cache.v1
```

It contains the active profile, UTC update timestamp, metric values and units.
Writing the cache does **not** perform another Modbus read. It is intended for
local read-only consumers such as ClearOS Webconfig, where the privileged local
helper can read the root-owned cache without opening the serial device.

## Stable metrics and MQTT

The stable metric catalog contains **89 metric IDs** under the
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

## Zabbix integration

The Zabbix Agent 2 integration examples remain available under:

```text
data/zabbix_agent2/
```

The repository includes the existing Zabbix visualization:

[![Zabbix Deye Agent Template](data/images/zabbix-deye-agent.png)](data/images/zabbix-deye-agent.png)

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

![Deye Agent web dashboard](data/images/deye-agent-dashboard-0.2.0.png)

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

Supported web languages:

```text
English
Українська
Polski
Deutsch
```

## RAM history

History is intentionally memory-only:

```text
HTTP_HISTORY_ENABLED=true
HTTP_HISTORY_MAX_SAMPLES=720
HTTP_HISTORY_RETENTION_SECONDS=21600
```

It is reset when the agent process starts again. Persistent on-disk history is
not part of release 0.2.1.

## Read-only register coverage

The supported profile includes validated read-only mappings for:

- Device information.
- Energy/statistics.
- PV/DC data.
- Real-time grid/inverter/load/battery telemetry.
- Warnings/fault status.
- Battery/BMS summary.
- Selected inverter settings.
- Selected system/status values.

Notable validated values include:

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

## License

Apache License 2.0.
