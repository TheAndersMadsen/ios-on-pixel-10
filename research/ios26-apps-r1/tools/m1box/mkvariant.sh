#!/bin/sh
# Build a root-image variant on m1box: reflink-copy BASE to NEW (btrfs, instant), mount it HFS+ read-write inside a
# privileged container, run EDIT.py against the mount point (python3 + plistlib, root inside the container), fsck.
# usage: mkvariant.sh BASE.img NEW.img EDIT.py [args...]   (paths under /data/hackios-qemu; EDIT.py gets MOUNT then args)
# The edit script is the whole variable of the run: keep it next to the run's receipt. hdiutil is not needed.
set -e
W=/data/hackios-qemu; BASE=$1; NEW=$2; EDIT=$3; shift 3
case "$BASE$NEW$EDIT" in *..*) echo "no .. in paths" >&2; exit 2;; esac
[ -s "$BASE" ] || { echo "missing base $BASE" >&2; exit 2; }
[ ! -e "$NEW" ] || { echo "refusing to overwrite $NEW" >&2; exit 2; }
cp --reflink=always "$BASE" "$NEW"
chmod u+w "$NEW"
rel() { case "$1" in /*) echo "${1#$W/}";; *) echo "$1";; esac; }
docker run --rm --privileged -v /lib/modules:/lib/modules:ro -v /dev:/dev -v "$W:/w" -w /w python:3.12-alpine sh -ec "
apk add -q hfsprogs util-linux-misc >/dev/null 2>&1
modprobe hfsplus 2>/dev/null || true
mkdir -p /m && mount -o loop -t hfsplus '/w/$(rel "$NEW")' /m
python3 -I '/w/$(rel "$EDIT")' /m $*
sync; umount /m
fsck.hfsplus -q '/w/$(rel "$NEW")'"
chmod a-w "$NEW"
sha256sum "$BASE" "$NEW"
