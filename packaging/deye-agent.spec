Name:           deye-agent
Version:        0.2.1
Release:        1%{?dist}
Summary:        Agent for retrieving and monitoring data from Deye inverters

License:        Apache-2.0
URL:            https://github.com/khvalera/deye-agent
Source0:        deye-agent-%{version}.tar.gz

BuildArch:      noarch

Requires:       python3
Requires:       python36-pyserial >= 3.4
Requires:       python36-PyYAML >= 5.3.1
Requires:       python36-paho-mqtt >= 1.5.0
Requires:       python3-chardet >= 3.0.4
Requires:       python3-idna >= 2.5
Requires:       systemd

%global python_site /usr/lib/python3.6/site-packages
%global unitdir /usr/lib/systemd/system

%description
Deye Agent is a read-only monitoring agent for Deye inverters connected over
RS485/Modbus RTU. It provides command-line diagnostics, normalized metrics,
MQTT publishing, a cached HTTP API, and an authenticated web dashboard.

%prep
%setup -q -n deye-agent-%{version}

%build
# Nothing to compile. The Python package is copied directly during install.

%install
rm -rf %{buildroot}

# Python package.
install -d -m 0755 %{buildroot}%{python_site}
cp -a deye_agent %{buildroot}%{python_site}/

# Never ship stale bytecode from the source tree.
find %{buildroot}%{python_site}/deye_agent \
  -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find %{buildroot}%{python_site}/deye_agent \
  -type d -name '__pycache__' -prune -exec rm -rf {} +

# CLI entry point.
install -d -m 0755 %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/deye-agent <<'EOF_SCRIPT'
#!/bin/sh
exec /usr/bin/python3 -m deye_agent.cli "$@"
EOF_SCRIPT
chmod 0755 %{buildroot}%{_bindir}/deye-agent

# Persistent configuration and protocol maps.
install -d -m 0755 %{buildroot}%{_sysconfdir}/deye-agent
install -d -m 0755 %{buildroot}%{_sysconfdir}/deye-agent/profiles

install -m 0600 \
  data/etc/deye-agent/deye-agent.conf \
  %{buildroot}%{_sysconfdir}/deye-agent/deye-agent.conf

install -m 0644 \
  data/etc/deye-agent/alarms.yaml \
  %{buildroot}%{_sysconfdir}/deye-agent/alarms.yaml

install -m 0644 \
  data/etc/deye-agent/registers.yaml \
  %{buildroot}%{_sysconfdir}/deye-agent/registers.yaml

install -m 0644 \
  data/etc/deye-agent/profiles/single_phase_storage.yaml \
  %{buildroot}%{_sysconfdir}/deye-agent/profiles/single_phase_storage.yaml

install -m 0644 \
  data/etc/deye-agent/profiles/three_phase_storage.yaml \
  %{buildroot}%{_sysconfdir}/deye-agent/profiles/three_phase_storage.yaml

# systemd service.
install -d -m 0755 %{buildroot}%{unitdir}
install -m 0644 \
  data/etc/systemd/system/deye-agent.service \
  %{buildroot}%{unitdir}/deye-agent.service

%post
/usr/bin/systemctl daemon-reload >/dev/null 2>&1 || :

%preun
if [ "$1" -eq 0 ]; then
    /usr/bin/systemctl --no-reload disable deye-agent.service \
        >/dev/null 2>&1 || :
    /usr/bin/systemctl stop deye-agent.service \
        >/dev/null 2>&1 || :
fi

%postun
/usr/bin/systemctl daemon-reload >/dev/null 2>&1 || :
if [ "$1" -ge 1 ]; then
    /usr/bin/systemctl try-restart deye-agent.service \
        >/dev/null 2>&1 || :
fi

%files
%license LICENSE
%doc README.md README_UK.md CHANGELOG.md

%{_bindir}/deye-agent
%{python_site}/deye_agent

%dir %{_sysconfdir}/deye-agent
%config(noreplace) %{_sysconfdir}/deye-agent/deye-agent.conf
%config(noreplace) %{_sysconfdir}/deye-agent/alarms.yaml
%{_sysconfdir}/deye-agent/registers.yaml
%dir %{_sysconfdir}/deye-agent/profiles
%{_sysconfdir}/deye-agent/profiles/single_phase_storage.yaml
%{_sysconfdir}/deye-agent/profiles/three_phase_storage.yaml

%{unitdir}/deye-agent.service

%changelog
* Mon Sep 07 2026 khvalera <khvalera@ukr.net> - 0.2.1-1
- Added configurable alarm rules in alarms.yaml with low/high thresholds and hysteresis.
- Added Email, Matrix and MQTT alarm notification support.
- Added runtime telemetry cache for ClearOS Webconfig without extra RS485 reads.
- Added low battery temperature alert and cleaned alarm metadata from profiles.

* Sat Sep 05 2026 khvalera <khvalera@ukr.net> - 0.2.0-3
- Added complete ClearOS 7 RPM dependencies for the Python 3.6 runtime.
- Added explicit dependencies for pyserial, PyYAML, paho-mqtt, chardet and idna.

* Sat Sep 05 2026 khvalera <khvalera@ukr.net> - 0.2.0-2
- Added persistent configuration, protocol profiles and register map to RPM.
- Added systemd service unit and package lifecycle integration.
- Preserved user configuration on upgrades with %%config(noreplace).
- Removed stale Python bytecode from packaged source tree.
- Kept RPM v4/gzip build compatibility for ClearOS/EL7.

* Sat Sep 05 2026 khvalera <khvalera@ukr.net> - 0.2.0-1
- Added protocol profiles, snapshot/metrics APIs, reliable MQTT metrics,
  authenticated web dashboard, RAM history and expanded validated telemetry.
