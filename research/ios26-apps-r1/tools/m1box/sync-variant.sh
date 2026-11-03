#!/bin/sh
# Run ON m1box. Pull a root image that was built on the Mac, as a delta against a base image already on m1box:
# reflink-copy BASE to NEW, then rsync --inplace only the changed blocks over the phone-bridge/ssh link.
# A variant that changes a few files moves in minutes instead of the ~35 min a full 20 GiB copy takes on Wi-Fi.
# usage: sync-variant.sh MAC_PATH_UNDER_HACKIOS_RESEARCH BASE.img NEW.img
#   e.g. sync-variant.sh ios26-apps-r1/artifacts/apps-foo-r13.img artifacts/apps-umdinit-r12.img artifacts/apps-foo-r13.img
set -e
cd /data/hackios-qemu/research/ios26-apps-r1
SRC=$1; BASE=$2; NEW=$3
[ ! -e "$NEW" ] || { echo "refusing to overwrite $NEW" >&2; exit 2; }
cp --reflink=always "$BASE" "$NEW"; chmod u+w "$NEW"
rsync -a --inplace --no-whole-file --info=progress2 "anders-macbook-pro:Developer/personal/hackios/research/$SRC" "$NEW"
chmod a-w "$NEW"
sha256sum "$NEW"
