#!/bin/bash
set -euo pipefail

VERSION="${1:-0.2.0}"
TOPDIR="${HOME}/rpmbuild"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

SPECFILE="${SCRIPT_DIR}/deye-agent.spec"
TARBALL="${TOPDIR}/SOURCES/deye-agent-${VERSION}.tar.gz"

mkdir -p "${TOPDIR}/BUILD" \
         "${TOPDIR}/BUILDROOT" \
         "${TOPDIR}/RPMS" \
         "${TOPDIR}/SOURCES" \
         "${TOPDIR}/SPECS" \
         "${TOPDIR}/SRPMS"

git -C "${REPO_ROOT}" archive \
  --format=tar.gz \
  --prefix="deye-agent-${VERSION}/" \
  -o "${TARBALL}" \
  HEAD

cp "${SPECFILE}" "${TOPDIR}/SPECS/deye-agent.spec"

rpmbuild -ba "${TOPDIR}/SPECS/deye-agent.spec" \
  --define "_topdir ${TOPDIR}" \
  --define "_rpmformat 4" \
  --define "_binary_payload w9.gzdio" \
  --define "_source_payload w9.gzdio"
