#!/usr/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

command -v xgettext >/dev/null 2>&1 || {
    echo "xgettext is required" >&2
    exit 1
}
command -v msgmerge >/dev/null 2>&1 || {
    echo "msgmerge is required" >&2
    exit 1
}

POT="deye_agent/locale/deye-agent.pot"
TMP_POT="${POT}.tmp"

mapfile -t PY_FILES < <(find deye_agent -type f -name '*.py' -print | sort)

xgettext \
    --language=Python \
    --keyword=_ \
    --package-name=deye-agent \
    --msgid-bugs-address=khvalera@ukr.net \
    --from-code=UTF-8 \
    --output="$TMP_POT" \
    "${PY_FILES[@]}"

mv "$TMP_POT" "$POT"

for lang in en uk; do
    PO="deye_agent/locale/${lang}/LC_MESSAGES/deye-agent.po"
    mkdir -p "$(dirname "$PO")"

    if [[ -f "$PO" ]]; then
        msgmerge --update --backup=none "$PO" "$POT"
    else
        if [[ "$lang" == "uk" ]]; then
            LOCALE="uk_UA.UTF-8"
        else
            LOCALE="en_US.UTF-8"
        fi
        msginit \
            --locale="$LOCALE" \
            --no-translator \
            --input="$POT" \
            --output-file="$PO"
    fi
done

echo "Translation sources updated."
