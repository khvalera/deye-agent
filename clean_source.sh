#!/usr/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

find deye_agent -type d -name __pycache__ -prune -exec rm -rf {} +
find deye_agent -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
rm -rf build dist *.egg-info

echo "Generated Python/build artifacts removed."
