#!/usr/bin/env bash
# What CI runs. Host only: nothing here reaches a phone or needs research/.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
export PYTHONDONTWRITEBYTECODE=1

echo '== check_tracked self-test'
python3 -I .github/scripts/test_check_tracked.py

echo '== status data and README are in step'
python3 -I -m json.tool docs/status.json > /dev/null
python3 -I tools/readme_status.py --check

echo '== every Python file parses, every script reads'
git ls-files -z '*.py' | xargs -0 python3 -I -c 'import sys
for f in sys.argv[1:]: compile(open(f, "rb").read(), f, "exec")'
bash -n tools/bootios tools/build-next-boot.sh shim/build.sh

# The other tools tests (bootplan, boot_tools, image_tool, laguna_usb_config, next_boot) and shim's tests need
# inputs under research/, which is never committed, so they run on the owner's machine: docs/BUILD.md, Tests.
# Tests of captures in this list skip when the capture is absent; CI's skipped count shows how many.
echo '== tools tests that need no research/'
cd tools
for t in test_boot_summary test_decode_shim_stamps test_fullcheck test_phone_write test_usbcon_tool; do
  echo "-- $t"
  python3 "$t.py" 2>&1 | tail -n 3
  test "${PIPESTATUS[0]}" -eq 0
done
