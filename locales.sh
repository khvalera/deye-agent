#!/usr/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

command -v msgfmt >/dev/null 2>&1 || {
    echo "msgfmt is required" >&2
    exit 1
}

for lang in en uk; do
    PO="deye_agent/locale/${lang}/LC_MESSAGES/deye-agent.po"
    MO="deye_agent/locale/${lang}/LC_MESSAGES/deye-agent.mo"

    if [[ ! -f "$PO" ]]; then
        echo "Missing translation source: $PO" >&2
        exit 1
    fi

    msgfmt --check "$PO" -o "$MO"
done

echo "Translation catalogs compiled."
