# Deye Agent

[English](README.md) | [Українська](README_UK.md)

`deye-agent` — сумісний з Python 3.6 агент моніторингу інверторів Deye,
підключених через RS485/Modbus RTU. Він надає CLI-діагностику, нормалізовані
метрики, MQTT-публікацію, порогові сповіщення, кешований HTTP API та read-only
web dashboard.

Production-шлях навмисно залишається консервативним: звичайний моніторинг
використовує лише перевірені read-only регістри та не надає керування записом у
параметри інвертора.

## Основні зміни релізу 0.2.1

Реліз 0.2.1 зберігає read-only архітектуру опитування та API з 0.2.0 і додає
окремі правила тривог та локальну телеметрію для Webconfig.

- Додано окремий `/etc/deye-agent/alarms.yaml`, незалежний від Modbus
  register/profile map.
- Додано оператори `le` та `ge` з явним гістерезисом через окремі пороги alarm
  та clear.
- Додано довільні повідомлення alarm/clear з безпечними літеральними
  placeholders.
- Додано доставку тривог через Email, Matrix та MQTT.
- MQTT-тривоги мають стабільну JSON-схему `deye-agent.alarm.v1`.
- Додано підтримку boolean-порогів для агрегованих метрик `Has Warning` та
  `Has Fault`.
- `alarms.yaml` перечитується після зміни без перезапуску daemon.
- Додано `/run/deye-agent/telemetry.json`, який формується з уже прочитаних
  daemon-ом даних. Локальний UI може читати його без додаткового RS485-доступу.
- Legacy `alarm/cancel` поля прибрані з protocol profile; threshold policy тепер
  зберігається лише в `alarms.yaml`.
- Додано скрипти збірки source/RPM та release validation.
- RPM spec тепер пакує backend configuration, profiles, alarms та systemd unit.
- З release tree прибрані tracked Python bytecode/cache artifacts.

Пороги в `alarms.yaml` є прикладом для поточного перевіреного профілю. Перед
увімкненням каналів сповіщень перевір їх для конкретного інвертора,
акумулятора, вимог мережі та умов встановлення.

Повний список змін: [CHANGELOG.md](CHANGELOG.md) та
[docs/RELEASE_0.2.1.md](docs/RELEASE_0.2.1.md).

## Статус апаратної перевірки профілів

### `single_phase_storage`

Статус: **hardware-validated**.

Поточна перевірка виконувалась на **5 kW single-phase storage inverter**.
Точний ідентифікатор моделі цього інвертора поки не записаний, тому профіль
навмисно має назву за сімейством, а не за конкретною моделлю.

### `three_phase_storage`

Статус: **reference-only**.

Трифазна карта зберігається окремо, оскільки значення регістрів відрізняються
між однофазними та трифазними сімействами. Вона не використовується для
звичайного runtime polling до окремої апаратної перевірки.

## Вимоги

- Python **3.6+**.
- Linux.
- RS485-доступ до інвертора.
- `pyserial`, `PyYAML`, `paho-mqtt`, `chardet`, `idna`.

Поточне production-середовище ClearOS використовує Python 3.6.8.

## Встановлення

Встановлення Python package з source:

```bash
git clone https://github.com/khvalera/deye-agent.git
cd deye-agent
python3 setup.py install
```

Приклади backend-конфігурації знаходяться в:

```text
data/etc/deye-agent/
```

Hardware-validated runtime profile зазвичай встановлюється як:

```text
/etc/deye-agent/profiles/single_phase_storage.yaml
```

Файл threshold rules:

```text
/etc/deye-agent/alarms.yaml
```

RPM-пакет встановлює backend configuration, profiles, alarm rules та systemd
service як файли пакета. Конфігураційні файли мають `noreplace`, тому upgrade
пакета не повинен тихо замінювати локальну конфігурацію.

## Збірка release artifacts

Спочатку виконай release checks:

```bash
./release_check.sh
```

Створити source tarball з поточного Git ref:

```bash
./build_source.sh
```

За замовчуванням створюється:

```text
dist/deye-agent-0.2.1.tar.gz
```

Для RPM на системі з `rpmbuild`:

```bash
./build_rpm.sh
```

RPM build використовує ізольоване дерево `dist/rpmbuild/` і не змінює
системні RPM build directories.

## Приклади підключення RS485

У репозиторії залишаються початкові фотографії та схеми підключення для
USB-RS485 або RS485-UART-TTL адаптерів.

### RS485-UART-TTL

[![Підключення RS485-UART-TTL](data/images/RS485–UART-TTL.JPG)](data/images/RS485–UART-TTL.JPG)

### USB-RS485

[![Підключення USB-RS485 1](data/images/USB-RS485-1.png)](data/images/USB-RS485-1.png)

[![Підключення USB-RS485 2](data/images/USB-RS485-2.JPG)](data/images/USB-RS485-2.JPG)

> RS485 pinout може відрізнятися між сімействами інверторів. Перед
> підключенням перевір pinout саме для конкретного інвертора.

## Базове використання

Показати список protocol profiles:

```bash
deye-agent profiles
```

Прочитати поточну телеметрію:

```bash
deye-agent --profile single_phase_storage read
```

Прочитати повний read-only snapshot:

```bash
deye-agent --profile single_phase_storage snapshot --json
```

Прочитати normalized metrics:

```bash
deye-agent --profile single_phase_storage metrics --json
```

Запустити monitoring loop:

```bash
deye-agent \
  --config /etc/deye-agent/deye-agent.conf \
  --profile single_phase_storage \
  run
```

Доступні також read-only/diagnostic команди:

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

## Правила тривог

Alarm policy зберігається окремо від hardware register map:

```text
ALARMS_FILE=/etc/deye-agent/alarms.yaml
ALARM_CONFIRMATIONS=2
```

`alarms.yaml` schema version 1 підтримує:

```text
le  alarm, якщо value <= alarm; clear, якщо value >= cancel
ge  alarm, якщо value >= alarm; clear, якщо value <= cancel
```

Для `le` значення `cancel` повинно бути більшим за `alarm`. Для `ge` — меншим.
Так створюється гістерезис і зменшується швидке перемикання alarm/clear біля
одного порога.

Приклад:

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

Підтримувані placeholders:

```text
{name} {value} {unit} {alarm} {cancel} {profile}
```

Після коректної зміни файл перечитується без restart daemon. Якщо файл
невалідний, threshold notifications працюють за принципом fail closed, а
основний monitoring loop може продовжувати роботу.

Bundled rules охоплюють inverter fault/warning, низьку/високу grid voltage,
низьку/високу grid frequency, низький battery SOC, низьку/високу battery
temperature, високу IGBT temperature та високе load power.

### Канали сповіщень

Email та Matrix використовують існуючі global switches:

```text
NOTIFY_EMAIL_ENABLED=false
NOTIFY_MATRIX_ENABLED=false
```

MQTT alarm events повторно використовують існуючі broker settings:

```text
NOTIFY_MQTT_ENABLED=false
NOTIFY_MQTT_TOPIC=solar/deye/alarms
```

Якщо `NOTIFY_MQTT_TOPIC` порожній, використовується `<MQTT_TOPIC>/alarms`.

MQTT alarm message має стабільну JSON-схему:

```text
deye-agent.alarm.v1
```

Документ містить event `alarm` або `clear`, rule ID, metric name, current value,
unit, operator, alarm/clear thresholds, profile та rendered message.

## Локальний telemetry cache

Запущений daemon записує вже отриману телеметрію в:

```text
/run/deye-agent/telemetry.json
```

Schema:

```text
deye-agent.telemetry-cache.v1
```

Cache містить active profile, UTC update timestamp, metric values та units.
Його запис **не виконує додаткового Modbus read**. Він призначений для локальних
read-only consumers, зокрема ClearOS Webconfig, де privileged helper може читати
root-owned cache без відкриття serial device.

## Stable metrics та MQTT

Stable metric catalog містить **89 metric IDs** у схемі
`deye-agent.metrics.v1`.

Якщо увімкнено:

```text
MQTT_ENABLED=true
MQTT_METRICS_ENABLED=true
```

stable metrics публікуються в:

```text
<MQTT_TOPIC>/metrics/<stable.metric.id>
```

Legacy MQTT output також збережений.

MQTT client використовує MQTT 3.1.1, bounded connection/publish waits та явне
відстеження завершення publication.

## Інтеграція з Zabbix

Приклади Zabbix Agent 2 залишаються в:

```text
data/zabbix_agent2/
```

[![Zabbix Deye Agent Template](data/images/zabbix-deye-agent.png)](data/images/zabbix-deye-agent.png)

## HTTP API та dashboard

HTTP layer читає лише runtime cache. Відкриття або оновлення браузера
**не створює додаткових Modbus-запитів**.

Увімкнення:

```text
HTTP_API_ENABLED=true
HTTP_API_HOST=0.0.0.0
HTTP_API_PORT=8765
```

API endpoints:

```text
GET /api/v1/health
GET /api/v1/overview
GET /api/v1/history?minutes=60
GET /api/v1/metrics
GET /api/v1/snapshot
```

### Авторизація

Авторизація обов'язкова, якщо `HTTP_API_ENABLED=true`.

Створити password hash:

```bash
deye-agent auth-hash
```

Налаштування:

```text
HTTP_AUTH_USERNAME=admin
HTTP_AUTH_PASSWORD_HASH=pbkdf2_sha256$...
HTTP_AUTH_SESSION_SECONDS=43200
HTTP_AUTH_COOKIE_SECURE=false
```

Якщо username або password hash відсутній, HTTP API працює за принципом
**fail closed**.

Без валідної browser session:

```text
GET /           -> redirect to /login
GET /api/v1/*   -> HTTP 401
```

Паролі перевіряються через PBKDF2-HMAC-SHA256 із випадковим salt. Browser
sessions використовують випадкові server-side tokens у RAM. Session cookies
мають `HttpOnly` та `SameSite=Strict`.

`HTTP_AUTH_COOKIE_SECURE=true` використовуй лише коли браузер реально звертається
до сервісу через HTTPS.

> Звичайний HTTP не шифрує login/password у мережі. Для захисту credentials
> використовуй HTTPS або довірену ізольовану мережу.

## Dashboard

![Web dashboard Deye Agent](data/images/deye-agent-dashboard-0.2.0.png)

Dashboard не має зовнішніх залежностей і читає `/api/v1/overview` та history
endpoint. Він показує grid, inverter, load, battery/BMS, PV, daily energy,
operating status, configuration summary та RAM-only historical charts.

Підтримувані web-мови:

```text
English
Українська
Polski
Deutsch
```

## RAM history

History навмисно зберігається лише в RAM:

```text
HTTP_HISTORY_ENABLED=true
HTTP_HISTORY_MAX_SAMPLES=720
HTTP_HISTORY_RETENTION_SECONDS=21600
```

Після нового запуску процесу history починається заново. Persistent on-disk
history не входить у реліз 0.2.1.

## Read-only покриття регістрів

Підтримуваний профіль містить перевірені read-only mappings для:

- Device information.
- Energy/statistics.
- PV/DC data.
- Real-time grid/inverter/load/battery telemetry.
- Warnings/fault status.
- Battery/BMS summary.
- Selected inverter settings.
- Selected system/status values.

Важливі hardware-validated значення:

```text
Register 79  -> Grid input frequency, scale 0.01 Hz
Register 150 -> Grid input voltage, scale 0.1 V
Register 154 -> Inverter output voltage, scale 0.1 V
```

Reserved або revision-sensitive регістри не отримують семантику без перевірки.

## Надійність RS485

Read path включає:

- Exclusive serial-open mode, якщо підтримується.
- Configurable retry attempts.
- Retry delay.
- Exact response length validation.
- Slave-ID validation.
- Function-code validation.
- Byte-count validation.
- CRC validation.
- Process-wide Linux abstract UNIX-socket lock навколо доступу до інвертора.

Normal telemetry зберігає open/read/close cycle. Combined snapshot використовує
одну shared serial session для coalesced read blocks.

## Ліцензія

Apache License 2.0.
