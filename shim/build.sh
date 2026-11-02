#!/bin/bash
# teguload v2 shim: quiesce + fb probe + runtime MPIDR + fault-gated findings,
# with the device handoff admitted (loader.c window policy). The QEMU-only
# scratch-fb profile stays opt-in: EXTRA_CFLAGS=-DTGL_QEMU_TEST.
# EXTRA_CFLAGS=-DTGL_WDT_KEEP keeps the firmware watchdogs (lab posture).
# UFS route gates are in tgl_ufs_route.h. Default: link, post-link and READ on, handoff off. TGL_UFS_HANDOFF=1 in the
# environment turns the handoff on. EXTRA_CFLAGS=-DTGL_UFS_READ=0 and the like turn one off.
set -euo pipefail
# Resolve the payload arg to an absolute path before cd-ing into shim/.
payload=${1:-}
if [ -n "$payload" ]; then
	payload=$(cd "$(dirname "$payload")" && pwd)/$(basename "$payload")
fi
# -P: shim/ is also reached through the teguload/shim symlink. ".." below must
# mean the repo root on either path, as the kernel resolves it physically.
cd -P "$(dirname "${BASH_SOURCE[0]}")"
if command -v aarch64-linux-gnu-gcc >/dev/null 2>&1; then
	CC=aarch64-linux-gnu-gcc
	OBJCOPY=aarch64-linux-gnu-objcopy
	READELF=aarch64-linux-gnu-readelf
	NM=aarch64-linux-gnu-nm
	LINK() { $CC $CFLAGS -static -T shim.ld -Wl,--build-id=none -Wl,--no-warn-rwx-segments -Wl,-N "$@"; }
else
	LLVM=${LLVM:-/opt/homebrew/opt/llvm/bin}
	CC="$LLVM/clang -target aarch64-unknown-none-elf"
	OBJCOPY="$LLVM/llvm-objcopy"
	READELF="$LLVM/llvm-readelf"
	NM="$LLVM/llvm-nm"
	# ld.lld directly: the clang driver would hand the GNU-style flags to the
	# host Apple ld (repo pattern: blazer/shim/build.py invokes ld.lld).
	LD=$(command -v ld.lld || true)
	[ -n "$LD" ] || [ -x "$LLVM/ld.lld" ] && LD="${LD:-$LLVM/ld.lld}"
	LINK() { "$LD" -nostdlib -static -T shim.ld --build-id=none -N "$@"; }
fi
HOSTCC=${HOSTCC:-cc}
# -fno-jump-tables: clang lowers switch/string-selection into static ABS64
# pointer tables, which the no-relocation image contract forbids (the check
# below). gcc kept branchy code; force it for both.
CFLAGS="-O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -fno-jump-tables -Wall -Wextra ${EXTRA_CFLAGS:-}"
mkdir -p out
# Per-build TSHIMST1 nonce: stamps recorded by a previous image of a
# different build can never be mistaken for this boot's history.
NONCE=0x$(python3 -c "import hashlib,time,sys;print(hashlib.sha256(str(time.time_ns()).encode()+sys.argv[1].encode()).hexdigest()[:16])" "$PWD")
echo "TSHIMST2 nonce: $NONCE"
printf '%s\n' "$NONCE" > out/stamp-nonce.txt
CFLAGS="$CFLAGS -DTGL_STAMP_NONCE=${NONCE}ULL"
# Per-build record identity: a decoder refuses a record of any other build.
TGL_UFS_HANDOFF=${TGL_UFS_HANDOFF:-0}
case "$TGL_UFS_HANDOFF" in 0|1) ;; *) echo "TGL_UFS_HANDOFF must be 0 or 1" >&2; exit 1 ;; esac
UFS_IDS=$(python3 -I - "$NONCE" out/ufs-ids.json "$TGL_UFS_HANDOFF" <<'PY'
import hashlib, json, sys, time
nonce, path, handoff = sys.argv[1:4]
record = hashlib.sha256(nonce.encode() + b"record").digest()[:16]
epoch = "0x%x" % (int(time.strftime("%Y%m%d%H%M")) )
json.dump(dict(stamp_nonce=nonce, epoch=epoch, record_nonce=record.hex(), handoff=int(handoff)), open(path, "w"))
print(epoch, "{" + ",".join("0x%02x" % b for b in record) + "}")
PY
)
UFS_EPOCH=${UFS_IDS%% *}
UFS_NONCE16=${UFS_IDS#* }
CFLAGS="-DTGL_UFS_ROUTE=1 -DTGL_UFS_POST_LINK=1 -DTGL_UFS_HANDOFF=$TGL_UFS_HANDOFF -DTGL_STAMP_UFS_FOCUS=1 -DTGL_UFS_EPOCH=${UFS_EPOCH}ULL -DTGL_UFS_RECORD_NONCE=$UFS_NONCE16 $CFLAGS"
for f in start.S shim.c console.c mmu.c fdt.c loader.c probe.c wdt.c laguna_usb.c laguna_usb_dma.c tgl_cpm.c tgl_display.c tgl_display_power.c tgl_usb_console.c tgl_ufs.c tgl_ufs_link.c tgl_ufs_host.c tgl_ufs_handoff.c tgl_ufs_route.c stamp.c guard.S ${TGL_EXTRA_SRC:-}; do
	$CC $CFLAGS -c $f -o out/${f%.*}.o
done
# all-r1 stages, named by ../research/ui-integrate-r1/build.py; empty otherwise.
EXTRA_O=$(for f in ${TGL_EXTRA_SRC:-}; do printf 'out/%s.o ' "${f%.*}"; done)
# The image runs wherever ABL puts it with no relocation pass: only the
# header's image_size (start.o, linked at 0) may be an absolute address.
abs=$($READELF -r out/shim.o out/console.o out/mmu.o out/fdt.o out/loader.o out/probe.o out/wdt.o out/laguna_usb.o out/laguna_usb_dma.o out/tgl_cpm.o out/tgl_display.o out/tgl_display_power.o out/tgl_usb_console.o out/tgl_ufs.o out/tgl_ufs_link.o out/tgl_ufs_host.o out/tgl_ufs_handoff.o out/tgl_ufs_route.o out/stamp.o out/guard.o $EXTRA_O | grep -c ABS64 || true)
[ "$abs" = 0 ] || { echo "error: $abs absolute relocations in C objects" >&2; exit 1; }
LINK out/start.o out/shim.o out/console.o out/mmu.o out/fdt.o out/loader.o out/probe.o out/wdt.o out/laguna_usb.o out/laguna_usb_dma.o out/tgl_cpm.o out/tgl_display.o out/tgl_display_power.o out/tgl_usb_console.o out/tgl_ufs.o out/tgl_ufs_link.o out/tgl_ufs_host.o out/tgl_ufs_handoff.o out/tgl_ufs_route.o out/stamp.o out/guard.o $EXTRA_O -o out/shim.elf
$OBJCOPY -O binary out/shim.elf out/Image
# ABL copies the file; pad to image_size so .bss/stacks exist as zeroed bytes.
size=$($NM out/shim.elf | awk '$3=="_end"{print $1}')
truncate -s "$((16#$size))" out/Image
# Ramdisk: an xnu payload (../tools/mkpayload.py) if given as $1, else an empty
# newc cpio (ABL dislikes a zero-size ramdisk on some builds) -> admission refusal and PSCI reset.
if [ -n "$payload" ]; then
	# B1 entry contract §5: embed the TEGUPLD1 envelope directly after _end
	# and raise the arm64 Image image_size (u64 at _head+16) so
	# tgl_payload_embedded() finds it (tegu build.sh semantics; payload.h).
	python3 - out/Image "$payload" <<'PY'
import struct, sys
img, pl = sys.argv[1], sys.argv[2]
f = open(img, "r+b")
f.seek(0, 2); end = f.tell()
pl = open(pl, "rb").read()
f.write(b"TEGUPLD1" + struct.pack("<Q", len(pl)) + pl)
f.seek(16)
f.write(struct.pack("<Q", end + 16 + len(pl)))
f.close()
print(f"envelope embedded: _end={end} payload={len(pl)} image_size={end + 16 + len(pl)}")
PY
	# tegu semantics: ramdisk_size = 0 — the embedded envelope IS the
	# delivery; shipping it twice busts the 64 MiB budget (v46 lesson).
	(cd out && rm -rf rd && mkdir rd && cd rd && find . | cpio -o -H newc --quiet | gzip -9 > ../ramdisk.bin)
else
	(cd out && rm -rf rd && mkdir rd && cd rd && find . | cpio -o -H newc --quiet | gzip -9 > ../ramdisk.bin)
fi
python3 ../tools/mkbootimg.py --header_version 4 --kernel out/Image --ramdisk out/ramdisk.bin \
	--os_version 17.0.0 --os_patch_level 2026-09 -o out/shim-boot-laguna.img
# Host render of the console layout (stamp channel redirected to a host sink),
# then the stamp deadline regression suite on a host-driven arch timer.
$HOSTCC -O1 -Wall -DTGL_STAMP_HOST -DTGL_STAMP_HOST_CLOCK -o out/host_test console.c laguna_usb.c stamp.c stamp_deadline_test.c host_test.c && ./out/host_test
# The UFS route, against the phone's recorded replies. A failure fails build.sh.
python3 -I test_ufs_route.py
# ufs-speed-r1: the same fake with the power mode change on.
python3 -I test_ufs_speed.py
# all-r1: the fallback and the PHY check, on the same fake.
if [ -f test_all_stages.py ]; then python3 -I test_all_stages.py; fi
# The DPU stage on a fake bus, gate TGL_DCS_BRIGHT off and on. No mutants here: run test_dcs_bright.py itself for those.
if [ -f test_dcs_bright.py ]; then python3 -I test_dcs_bright.py --quick; fi
# A2 chooser: menu/segment/placement and the lz4 decoder on hand-made inputs.
# tools/chooser_image.py reruns both binaries on the real A0 kernel and FDT.
if [ -f chooser_test.c ]; then
	$HOSTCC -O1 -Wall -Wextra -DTGL_CHOOSER_HOST -o out/chooser_test chooser.c fdt.c chooser_test.c && ./out/chooser_test
	$HOSTCC -O2 -Wall -Wextra -o out/lz4_test lz4.c lz4_test.c && ./out/lz4_test
	$HOSTCC -O1 -Wall -Wextra -DTGL_CHOOSER_HOST -o out/el2_mmu_test el2_mmu.c fdt.c el2_mmu_test.c && ./out/el2_mmu_test
	$HOSTCC -O2 -Wall -Wextra -o out/menu_ui_preview menu_ui.c menu_ui_preview.c && ./out/menu_ui_preview out/menu
fi
ls -l out/Image out/shim-boot-laguna.img
