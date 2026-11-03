#!/bin/sh
# usage: ro-run.sh IMG SCRIPT.py [args]  -- mount IMG read-only (hfsplus, loop) in the privileged container, run SCRIPT /m args
set -e
W=/data/hackios-qemu; IMG=$1; S=$2; shift 2
rel() { case "$1" in /*) echo "${1#$W/}";; *) echo "$1";; esac; }
docker run --rm --privileged -v /lib/modules:/lib/modules:ro -v /dev:/dev -v "$W:/w" -w /w python:3.12-alpine sh -ec "
apk add -q hfsprogs util-linux-misc attr >/dev/null 2>&1
modprobe hfsplus 2>/dev/null || true
mkdir -p /m && mount -o loop,ro -t hfsplus '/w/$(rel "$IMG")' /m
python3 -I '/w/$(rel "$S")' /m $*
umount /m"
