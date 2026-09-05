# Changelog

All notable changes to Deye Agent are documented here.

## 0.2.0 - 2026-09-05

### RS485 / Modbus
- Preserved Python 3.6.8 compatibility.
- Added retry-based RS485 read reliability.
- Added strict validation of response length, slave ID, function code,
  byte count and CRC.
- Added process-wide inverter access locking.
- Added coalesced snapshot reads using one shared serial session.

### Protocol profiles and read-only data
- Added `single_phase_storage` as the supported hardware-validated profile.
- Added `three_phase_storage` as a separate reference-only profile.
- Added read-only device information, battery/BMS, settings, system status,
  inventory and combined snapshot commands.
- Expanded validated energy, PV/DC, real-time, warning/fault and relay
  telemetry.
- Added hardware-validated Grid Frequency (register 79).
- Added hardware-validated Inverter Output Voltage (register 154).

### Metrics and MQTT
- Added `deye-agent.metrics.v1`.
- Stable catalog now contains 89 metric IDs.
- Added stable MQTT topics under `<MQTT_TOPIC>/metrics/<metric.id>`.
- Added MQTT connection and publication completion handling with bounded
  timeouts.
- Preserved legacy MQTT publishing.

### HTTP API
- Added cached read-only API endpoints for health, overview, history, metrics
  and snapshot.
- API reads runtime state only; web clients do not initiate RS485 reads.
- Added atomic overview generation and acquisition/quality metadata.

### Web dashboard
- Added responsive dependency-free dashboard.
- Added RAM-only history charts.
- Added English, Ukrainian, Polish and German web translations.
- Added stable numeric precision for voltage/current/frequency presentation.
- Clarified grid relay wording.
- Added grid input frequency and inverter output voltage to the UI/history.

### Authentication
- Added `deye-agent auth-hash`.
- Added PBKDF2-HMAC-SHA256 password hashing.
- Added RAM-only authenticated sessions.
- Added `HttpOnly` + `SameSite=Strict` session cookies.
- Added login and logout UI.
- Authentication is mandatory whenever `HTTP_API_ENABLED=true`.
- Missing credentials fail closed.
- Anonymous dashboard access redirects to `/login`.
- Anonymous `/api/v1/*` requests return HTTP 401.

### Packaging/documentation
- Version bumped to 0.2.0.
- Python requirement aligned to Python >=3.6.
- License metadata aligned to Apache-2.0.
- Web assets included in setuptools package data.
- Documentation updated for profiles, metrics, API, dashboard and auth.

## 0.1.1 - 2026-09-02

- Improved RS485 / Modbus communication reliability.
- Added automatic retry for failed register reads.
- Added validation of Modbus response length, slave ID, function code,
  byte count and CRC.
- Added exclusive serial-port access.
- Improved RS485 debug output.

## 0.1.0

- Initial public release.
- RS485 telemetry.
- MQTT publishing.
- Linux/systemd deployment examples.
- Zabbix integration examples.
