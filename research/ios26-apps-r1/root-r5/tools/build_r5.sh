#!/bin/sh
# root-r5 on m1box: BASE (phone r4 a6574777..., or the QEMU twin) + the stock files r3's prune removed
#   files/r5-files.tar  (2a9eed19) the Phone/About/AX bundles (r5-filelist.txt, completed per bundle; 141 files)
#   files/r5b-files.tar (a5ee096a) the int3 crash-stack set: LinkPresentation + OnBoardingKit Assets.car, OnBoardingBundles,
#                                  AppPlaceholders (1060 files)
# + replaced files: files/changed.tar (3f26ff94, Mac reseal of MobilePhone.app) and files/skel.tar (47ee62e6, var.skel.tsv
#   + iTunes_Control).
# usage: build_r5.sh BASE BASE_SHA256 OUT   (from /data/hackios-qemu; relative paths)
set -eu
W=/data/hackios-qemu; D=research/ios26-apps-r1/root-r5; cd $W
BASE=$1; BSHA=$2; OUT=$3
echo "$BSHA  $BASE" | sha256sum -c
sha256sum -c <<SUMS
2a9eed192acf75cd239028785cd15e4d3e1532ed4db334e96f04392785a7dd20  $D/files/r5-files.tar
a5ee096a62973376fcb2f70e62111cd175ac2f2ca1c6e134d92fee4a1ba229fc  $D/files/r5b-files.tar
3f26ff942f5c3b845be03505d1e07f53a21643d75151a3e9556a7b3d3abd93cc  $D/files/changed.tar
47ee62e6c0ce5ed9295676c91518d314f162c57f5cdcfd2838becf8a5d4e40d6  $D/files/skel.tar
SUMS
[ ! -e $OUT ] || { echo "refusing to overwrite $OUT" >&2; exit 2; }
mkdir -p $(dirname $OUT); cp --reflink=auto $BASE $OUT.tmp; chmod u+w $OUT.tmp
docker run --rm --privileged -v /lib/modules:/lib/modules:ro -v /dev:/dev -v "$W:/w" -w /w python:3.12-alpine sh -ec "
apk add -q hfsprogs util-linux-misc >/dev/null 2>&1
modprobe hfsplus 2>/dev/null || true
echo '--- fsck before'; fsck.hfsplus -f -n /w/$OUT.tmp
mkdir -p /m && mount -o loop,rw,nls=utf8,noatime -t hfsplus /w/$OUT.tmp /m
python3 -I /w/$D/tools/insert_r5.py /m /w/$D/files/r5-files.tar,/w/$D/files/r5b-files.tar /w/$D/files/changed.tar,/w/$D/files/skel.tar /w/$OUT.insert.json
sync; umount /m
echo '--- fsck after insert'; fsck.hfsplus -f -n /w/$OUT.tmp"
python3 -I research/ios26-apps-r1/root-r4/tools/sync_alt_vh.py $OUT.tmp
mv $OUT.tmp $OUT; chmod a-w $OUT
sha256sum $OUT
