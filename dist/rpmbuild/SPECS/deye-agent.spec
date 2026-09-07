Name:           deye-agent
Version:        0.2.1
Release:        1%{?dist}
Summary:        Agent for retrieving and monitoring data from Deye inverters

License:        Apache-2.0
URL:            https://github.com/khvalera/deye-agent
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  python3-pyyaml
Requires:       python3
Requires:       python3-pyyaml
Requires:       python3-pyserial
Requires:       python3-paho-mqtt
Requires:       systemd

%description
Agent for retrieving and monitoring data from Deye inverters over RS485/Modbus
RTU, with MQTT publishing, alarm notifications and a cached HTTP dashboard.

%prep
%setup -q

%build
# The ClearOS packaging path copies the Python package directly.

%install
rm -rf %{buildroot}

mkdir -p %{buildroot}%{_prefix}/lib/python3.6/site-packages/
cp -a deye_agent %{buildroot}%{_prefix}/lib/python3.6/site-packages/
find %{buildroot}%{_prefix}/lib/python3.6/site-packages/deye_agent \
    -type d -name __pycache__ -prune -exec rm -rf {} +
find %{buildroot}%{_prefix}/lib/python3.6/site-packages/deye_agent \
    -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete

mkdir -p %{buildroot}%{_bindir}
cat > %{buildroot}%{_bindir}/deye-agent <<'SCRIPT'
#!/bin/sh
exec /usr/bin/python3 -m deye_agent.cli "$@"
SCRIPT
chmod 0755 %{buildroot}%{_bindir}/deye-agent

mkdir -p %{buildroot}%{_sysconfdir}/deye-agent/profiles
install -m 0640 data/etc/deye-agent/deye-agent.conf \
    %{buildroot}%{_sysconfdir}/deye-agent/deye-agent.conf
install -m 0644 data/etc/deye-agent/alarms.yaml \
    %{buildroot}%{_sysconfdir}/deye-agent/alarms.yaml
install -m 0644 data/etc/deye-agent/registers.yaml \
    %{buildroot}%{_sysconfdir}/deye-agent/registers.yaml
install -m 0644 data/etc/deye-agent/profiles/single_phase_storage.yaml \
    %{buildroot}%{_sysconfdir}/deye-agent/profiles/single_phase_storage.yaml
install -m 0644 data/etc/deye-agent/profiles/three_phase_storage.yaml \
    %{buildroot}%{_sysconfdir}/deye-agent/profiles/three_phase_storage.yaml

mkdir -p %{buildroot}%{_unitdir}
install -m 0644 data/etc/systemd/system/deye-agent.service \
    %{buildroot}%{_unitdir}/deye-agent.service

%post
/bin/systemctl daemon-reload >/dev/null 2>&1 || :

%postun
/bin/systemctl daemon-reload >/dev/null 2>&1 || :

%files
%license LICENSE
%doc README.md README_UK.md CHANGELOG.md docs/RELEASE_0.2.1.md
%{_prefix}/lib/python3.6/site-packages/deye_agent
%{_bindir}/deye-agent
%config(noreplace) %{_sysconfdir}/deye-agent/deye-agent.conf
%config(noreplace) %{_sysconfdir}/deye-agent/alarms.yaml
%config(noreplace) %{_sysconfdir}/deye-agent/registers.yaml
%config(noreplace) %{_sysconfdir}/deye-agent/profiles/single_phase_storage.yaml
%config(noreplace) %{_sysconfdir}/deye-agent/profiles/three_phase_storage.yaml
%{_unitdir}/deye-agent.service

%changelog
* Mon Sep 07 2026 khvalera <khvalera@ukr.net> - 0.2.1-1
- Added standalone alarm rules with le/ge hysteresis and custom messages.
- Added Email, Matrix and MQTT alarm delivery.
- Added local telemetry cache for read-only Webconfig consumers.
- Updated source/RPM build and release tooling.

* Sat Sep 05 2026 khvalera <khvalera@ukr.net> - 0.2.0-1
- Added protocol profiles, snapshot/metrics APIs, reliable MQTT metrics,
  authenticated web dashboard, RAM history and expanded validated telemetry.

* Fri Nov 19 2025 Your Name <youremail@example.com> - 0.1.0-1
- Initial RPM release
