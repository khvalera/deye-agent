#!/usr/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

python3 - <<'PY'
import ast
import os
import re
import sys

import yaml

EXPECTED = '0.2.1'

namespace = {}
with open('deye_agent/__init__.py', 'r', encoding='utf-8') as handle:
    exec(handle.read(), namespace)
if namespace.get('__version__') != EXPECTED:
    raise SystemExit('deye_agent/__init__.py version mismatch')

checks = {
    'setup.py': 'version="{}"'.format(EXPECTED),
    'pyproject.toml': 'version = "{}"'.format(EXPECTED),
    'deye-agent.spec': 'Version:        {}'.format(EXPECTED),
    'README.md': 'Release {} highlights'.format(EXPECTED),
    'README_UK.md': 'релізу {}'.format(EXPECTED),
    'CHANGELOG.md': '## {} -'.format(EXPECTED),
}
for path, needle in checks.items():
    with open(path, 'r', encoding='utf-8') as handle:
        text = handle.read()
    if needle not in text:
        raise SystemExit('{} does not contain {!r}'.format(path, needle))

for root, dirs, files in os.walk('deye_agent'):
    dirs[:] = [name for name in dirs if name != '__pycache__']
    for filename in files:
        if not filename.endswith('.py'):
            continue
        path = os.path.join(root, filename)
        with open(path, 'r', encoding='utf-8') as handle:
            source = handle.read()
        ast.parse(source, filename=path)

for path in (
        'data/etc/deye-agent/profiles/single_phase_storage.yaml',
        'data/etc/deye-agent/registers.yaml'):
    with open(path, 'r', encoding='utf-8') as handle:
        document = yaml.safe_load(handle) or {}
    registers = document.get('registers', []) or []
    forbidden = {'alarm', 'cancel', 'alarm_emoji', 'cancel_emoji'}
    for register in registers:
        bad = forbidden.intersection(register)
        if bad:
            raise SystemExit('{} contains legacy alarm fields: {}'.format(
                path, ', '.join(sorted(bad))))

with open('data/etc/deye-agent/alarms.yaml', 'r', encoding='utf-8') as handle:
    alarms_text = handle.read()
    alarms_doc = yaml.safe_load(alarms_text) or {}

if re.search(r'[\u0400-\u04ff]', alarms_text):
    raise SystemExit('alarms.yaml contains Cyrillic text; repository defaults must be English')

if alarms_doc.get('version') != 1:
    raise SystemExit('alarms.yaml schema version must be 1')

rules = alarms_doc.get('alarms') or {}
if not isinstance(rules, dict) or not rules:
    raise SystemExit('alarms.yaml contains no alarm rules')

for rule_id, rule in rules.items():
    operator = rule.get('operator')
    alarm = rule.get('alarm')
    cancel = rule.get('cancel')
    if operator == 'le' and not cancel > alarm:
        raise SystemExit('{}: le requires cancel > alarm'.format(rule_id))
    if operator == 'ge' and not cancel < alarm:
        raise SystemExit('{}: ge requires cancel < alarm'.format(rule_id))
    if operator not in ('le', 'ge'):
        raise SystemExit('{}: invalid operator {}'.format(rule_id, operator))

print('VERSION={}'.format(EXPECTED))
print('PYTHON_SYNTAX=OK')
print('PROFILE_REGISTERS={}'.format(len(
    yaml.safe_load(open('data/etc/deye-agent/profiles/single_phase_storage.yaml', encoding='utf-8'))['registers']
)))
print('PROFILE_ALARM_FIELDS=0')
print('ALARM_RULES={}'.format(len(rules)))
print('ALARM_HYSTERESIS=OK')
print('ALARMS_ENGLISH_ONLY=OK')
PY

if find deye_agent -type f \( -name '*.pyc' -o -name '*.pyo' \) -print -quit | grep -q .; then
    echo "Generated Python bytecode exists in the source tree" >&2
    exit 1
fi
if find deye_agent -type d -name __pycache__ -print -quit | grep -q .; then
    echo "__pycache__ exists in the source tree" >&2
    exit 1
fi

if command -v git >/dev/null 2>&1 && [[ -d .git ]]; then
    if git ls-files | grep -E '(^|/)(__pycache__/|.*\.py[co]$)' >/dev/null; then
        echo "Tracked Python bytecode/cache files must be removed before release" >&2
        exit 1
    fi
fi

for script in build_source.sh build_rpm.sh release_check.sh clean_source.sh make_po.sh locales.sh; do
    bash -n "$script"
done

echo "BYTECODE_TREE=OK"
echo "SHELL_SYNTAX=OK"
echo "RELEASE_CHECK=OK"
