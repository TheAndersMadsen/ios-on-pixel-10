#!/bin/sh
# root-r4 on m1box: r3 (205cb0e2...) -> grow to the 24 GiB ios_system (6291456 blocks) -> + the 49 staged bundles.
# usage: build_r4.sh   (from /data/hackios-qemu; writes research/ios26-apps-r1/root-r4/out/ios26-phone-r4.img)
set -eu
W=/data/hackios-qemu; D=research/ios26-apps-r1/root-r4; cd $W
R3=$D/src/ios26-phone-r3.img; OUT=$D/out/ios26-phone-r4.img
echo "205cb0e2887aeee1454c82fdb57a95e0b4f0443f738bcab6d387c4bb9462d9b7  $R3" | sha256sum -c
mkdir -p $D/out; [ ! -e $OUT ] || { echo "refusing to overwrite $OUT" >&2; exit 2; }
cp --reflink=auto $R3 $OUT.tmp; chmod u+w $OUT.tmp
python3 -I $D/tools/hfs_grow.py $OUT.tmp 6291456
docker run --rm --privileged -v /lib/modules:/lib/modules:ro -v /dev:/dev -v "$W:/w" -w /w python:3.12-alpine sh -ec "
apk add -q hfsprogs util-linux-misc >/dev/null 2>&1
modprobe hfsplus 2>/dev/null || true
echo '--- fsck after grow'; fsck.hfsplus -f -n /w/$OUT.tmp
mkdir -p /m && mount -o loop,rw,nls=utf8,noatime -t hfsplus /w/$OUT.tmp /m
python3 -I /w/$D/tools/insert_apps.py /m /w/$D/apps/apps-r4.tar /w/$D/apps/src-owners.tsv
sync; umount /m
echo '--- fsck after insert'; fsck.hfsplus -f -n /w/$OUT.tmp"
python3 -I $D/tools/sync_alt_vh.py $OUT.tmp   # added after the a6574777 build ran: that build ran it as a separate step on the finished image
mv $OUT.tmp $OUT; chmod a-w $OUT
sha256sum $OUT
