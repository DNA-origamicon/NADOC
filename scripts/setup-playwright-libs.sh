#!/usr/bin/env bash
# Download and extract missing system libraries for Playwright's Chromium headless shell.
# Required because libnspr4 / libnss3 / libasound2 are not installed system-wide.
# Run this once after a reboot (libs land in /tmp and are cleared on restart).
#
# Usage: bash scripts/setup-playwright-libs.sh

set -euo pipefail

LIBDIR=/tmp/nspr-libs

if [[ -f "$LIBDIR/usr/lib/x86_64-linux-gnu/libnss3.so" ]]; then
  echo "Libs already present at $LIBDIR — nothing to do."
  exit 0
fi

echo "Downloading libnspr4, libnss3, libasound2t64..."
tmpdir=$(mktemp -d)
cd "$tmpdir"

apt download libnspr4 libnss3 libasound2t64 2>&1 | grep -E "Get:|already|Err:" || true

for deb in *.deb; do
  dpkg -x "$deb" "$LIBDIR"
done

echo "Done. Libraries extracted to $LIBDIR"
echo "Run: export LD_LIBRARY_PATH=$LIBDIR/usr/lib/x86_64-linux-gnu"
