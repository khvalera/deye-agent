Name:           deye-agent
Version:        0.2.0
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

%description
Agent for retrieving and monitoring data from Deye inverters.

%prep
%setup -q

%build
# The current ClearOS packaging path copies the Python package directly.

%install
rm -rf %{buildroot}
mkdir -p %{buildroot}%{_prefix}/lib/python3.6/site-packages/
cp -r deye_agent %{buildroot}%{_prefix}/lib/python3.6/site-packages/

mkdir -p %{buildroot}%{_bindir}
echo '#!/bin/sh' > %{buildroot}%{_bindir}/deye-agent
echo 'exec /usr/bin/python3 -m deye_agent.cli "$@"' >> %{buildroot}%{_bindir}/deye-agent
chmod +x %{buildroot}%{_bindir}/deye-agent

%files
%license LICENSE
%doc README.md CHANGELOG.md
%{_prefix}/lib/python3.6/site-packages/deye_agent
%{_bindir}/deye-agent

%changelog
* Sat Sep 05 2026 khvalera <khvalera@ukr.net> - 0.2.0-1
- Added protocol profiles, snapshot/metrics APIs, reliable MQTT metrics,
  authenticated web dashboard, RAM history and expanded validated telemetry.

* Fri Nov 19 2025 Your Name <youremail@example.com> - 0.1.0-1
- Initial RPM release
