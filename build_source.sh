#!/usr/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

./release_check.sh

VERSION="$(python3 - <<'PY'
namespace = {}
with open('deye_agent/__init__.py', 'r', encoding='utf-8') as handle:
    exec(handle.read(), namespace)
print(namespace['__version__'])
PY
)"

rm -rf build dist *.egg-info
python3 setup.py sdist --formats=gztar

ARCHIVE="dist/deye-agent-${VERSION}.tar.gz"
if [[ ! -f "$ARCHIVE" ]]; then
    echo "Source archive was not created: $ARCHIVE" >&2
    exit 1
fi

echo "SOURCE_ARCHIVE=$ARCHIVE"
