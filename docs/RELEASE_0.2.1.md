# Deye Agent 0.2.1

Release 0.2.1 extends the read-only monitoring architecture introduced in
0.2.0 with configurable alarm rules, MQTT alarm events and a local telemetry
cache intended for trusted local integrations such as ClearOS Webconfig.

## Alarm rules

Threshold policy is stored in `/etc/deye-agent/alarms.yaml`, separately from
the protocol/register profile. Each rule has a stable ID and supports:

- `enabled`
- `metric`
- `operator`: `le` or `ge`
- `alarm`
- `cancel`
- `message`
- `clear_message`

`le` triggers when the value is less than or equal to `alarm` and clears when
it is greater than or equal to `cancel`. `ge` applies the opposite direction.
`ALARM_CONFIRMATIONS` still controls the number of consecutive abnormal samples
required before a new alarm becomes active.

Rules are reloaded when `alarms.yaml` changes. Invalid files fail closed for
threshold notifications while normal inverter polling can continue.

The repository ships example thresholds for the currently validated
single-phase profile. They are not universal electrical or battery safety
limits and should be reviewed for the actual installation.

## Notification channels

Alarm and clear events can be delivered through Email, Matrix and MQTT. MQTT
alarm events reuse the existing broker connection settings and publish a stable
JSON document with schema `deye-agent.alarm.v1`.

Configuration keys:

```text
NOTIFY_EMAIL_ENABLED=false
NOTIFY_MATRIX_ENABLED=false
NOTIFY_MQTT_ENABLED=false
NOTIFY_MQTT_TOPIC=solar/deye/alarms
```

If `NOTIFY_MQTT_TOPIC` is empty, the topic defaults to
`<MQTT_TOPIC>/alarms`.

## Local telemetry cache

The running agent writes `/run/deye-agent/telemetry.json` after normal telemetry
acquisition. The cache contains the values already read by the daemon, their
units, the active profile and a UTC update timestamp.

Reading this file does not open the serial device and does not create additional
Modbus traffic. It is intended for trusted local consumers. The cache is
runtime-only and is recreated after service start.

## Packaging

Version metadata is aligned to 0.2.1 in setuptools, `pyproject.toml`, the Python
package and the RPM spec.

Release helpers:

```text
./clean_source.sh
./release_check.sh
./build_source.sh
./build_rpm.sh
```

The RPM owns backend configuration, alarm rules, register/profile files and the
systemd unit. Configuration files use `noreplace` semantics. Package scripts do
not automatically start or restart `deye-agent`.
