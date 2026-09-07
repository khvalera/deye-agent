#!/usr/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

command -v rpmbuild >/dev/null 2>&1 || {
    echo "rpmbuild is required" >&2
    exit 1
}

./build_source.sh

VERSION="$(python3 - <<'PY'
namespace = {}
with open('deye_agent/__init__.py', 'r', encoding='utf-8') as handle:
    exec(handle.read(), namespace)
print(namespace['__version__'])
PY
)"

TOPDIR="${RPM_TOPDIR:-$ROOT_DIR/rpmbuild}"
mkdir -p "$TOPDIR"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}

cp "dist/deye-agent-${VERSION}.tar.gz" "$TOPDIR/SOURCES/"
cp deye-agent.spec "$TOPDIR/SPECS/"

rpmbuild --define "_topdir $TOPDIR" -ba "$TOPDIR/SPECS/deye-agent.spec"

echo "RPM_TOPDIR=$TOPDIR"
find "$TOPDIR/RPMS" "$TOPDIR/SRPMS" -type f \
    \( -name '*.rpm' -o -name '*.src.rpm' \) -print
