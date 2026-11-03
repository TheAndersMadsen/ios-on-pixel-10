#!/bin/sh
# m1box QEMU calibration: replay the Mac's registration-umdinit-r12d intent (same kernel, root, overlay, boot-args, window)
# in TCG and in KVM, side by side. Evidence only: QEMU results say nothing about Tensor.
set -e
cd /data/hackios-qemu/research/ios26-apps-r1
IMG=artifacts/apps-umdinit-r12.img
while [ ! -s $IMG ] || ls artifacts/.apps-umdinit-r12.img.* >/dev/null 2>&1; do sleep 20; done
echo "image present $(date +%T): $(stat -c %s $IMG) bytes"
T=$(cat /data/hackios-qemu/ref-r12d/args-tail.txt)
export HACKIOS_QEMU_SLOTS=2
COMMON="--kernel ../ios26-release-r1/artifacts/kernel.ios26-p29 --root $IMG --window-gib 28 --ramdisk-root --var-overlay artifacts/hgltrack-rebuilt.ovl --args"
python3 -I tools/qemu-ufsroot.py cal-r12d-kvm --accel kvm --runtime ${KVM_RUNTIME:-600} --idle 0 $COMMON "$T" > /data/hackios-qemu/cal-kvm.out 2>&1 &
sleep 30
python3 -I tools/qemu-ufsroot.py cal-r12d-tcg --runtime ${TCG_RUNTIME:-1200} --idle 0 $COMMON "$T" > /data/hackios-qemu/cal-tcg.out 2>&1 &
wait
echo "both done $(date +%T)"
for n in cal-r12d-kvm cal-r12d-tcg; do echo "== $n"; cat runs/$n/exit.json; done
