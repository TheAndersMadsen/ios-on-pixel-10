#!/usr/bin/env bash
# Host-only builder for a parent-approved temporary next boot. No device access.
set -euo pipefail
ROOT=$(cd "$(dirname "$(realpath "$0")")/.." && pwd)
LANE="$ROOT/research/laguna-usb-console"
TL="$ROOT/research/workspace/hackios-xnu-kernel/blazer/teguload"
OUT=${OUT:-$LANE/out/next-boot}
R4_MACHO=${R4_MACHO:?"set R4_MACHO to the R4 msgbuf-mirror Mach-O"}
# Root of record (2026-10-26): the xnu.ramdisk bytes EMBEDDED IN the proven v6
# vendor_boot (out/blazer-devicerun-primary-vendor_boot-avb-v6.img, sha256
# 5a039972...) — i.e. the 24 MiB root actually staged as kexec md0 in the
# proven on-device ladder (probe log "ramdisk md0 ... bytes=25165824").
# The earlier pin b17e7fd9... referenced a work-dir file that was regenerated
# (now 4d9a9f59...) and no longer matches anything that ran on device.
ROOTFS=${ROOTFS:-$ROOT/research/laguna-deviceroot/work/bootstrap-root-proven-v6.hfs}
# --- root profile (P3, opt-in) -------------------------------------------
# WITH_ROOT7=1 swaps the 24 MiB v6 bootstrap root for the 28 MiB root-v7
# (research/laguna-usb-fix/root-upgrade/root-v7.hfs). Both roots are RAMDisk
# HFS+ md0 roots with the identical contract and IDENTICAL boot-args
# (rd=md0 rootrw=1 ignition_level=1 launchd_unsecure_cache=1; no
# rootfiledev/pageable/private tokens — those are physical-device/sleep
# tokens, not RAMDisk tokens).
# v7 is exactly 4 MiB larger. The shim refuses any payload whose ADT +
# boot_args top leaves <64 MiB headroom in the kernel window (payload.h
# "insufficient kernel headroom"; reproduced host-side via
# teguload/tests/host-admission.sh against the v54 control + a v7 payload
# on 2026-10-27), so this profile raises the ADT kernel window by 4 MiB
# (0x0A000000 -> 0x0A400000, still far from the mkadt ramoops guard).
# WITHOUT the flag this builder behaves exactly as before (same window,
# same v6 pin).
# Additive profiles pin both root and kernel; no implicit custom-root fallback.
# Existing WITH_ROOT profiles and default command line remain unchanged.
if [[ -n ${NEXT_BOOT_PROFILE:-} ]]; then
    {
        IFS= read -r ROOTFS
        IFS= read -r ROOT_TAG
        IFS= read -r ROOT_PIN
        IFS= read -r MEMSIZE
        IFS= read -r PROFILE_CMDLINE
        IFS= read -r PROFILE_ADT_PATH
        IFS= read -r PROFILE_VALIDATED
    } < <(python3 "$LANE/tools/validate-next-boot-profile.py" "$NEXT_BOOT_PROFILE" "$R4_MACHO")
    [[ $PROFILE_VALIDATED = VALIDATED ]] || { echo 'profile validation failed' >&2; exit 1; }
elif [[ ${WITH_ROOT20:-0} = 1 ]]; then
    # root-v20 (D5): root-v19 + D5 diag dyld (9 unconditional load-phase
    # L-markers: L1 depCount / L9 ncmds / L6 loaded-count VALUE channels)
    # — names the dead dependent-load stage in one boot.
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v20.hfs
    ROOT_TAG=root-v20
    ROOT_PIN='29360128:0c57f377499c8c16d36bc37629521ef99d417bfc73e7a8903460536f9982bd67'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT19:-0} = 1 ]]; then
    # root-v19 (P1b): root-v18 + P1b dyld (volatile-store bzero — fixes the
    # LLVM self-tail-call infinite loop at _bzero; DyldCommPageC1 was the
    # first caller) + marker lengths repaired (32 unique, script-asserted)
    # + B1 ctor-entry marker + V3K refused-FIXED kern_return_t channel.
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v19.hfs
    ROOT_TAG=root-v19
    ROOT_PIN='29360128:a72f6d95207585c52e7e3bad2ccd376181b8fa0ba195c840a7ec9ae2bc583362'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT18:-0} = 1 ]]; then
    # root-v18 (P1): root-v17 + patch 0007 (deterministic FIXED-first
    # pre-prepare VM placement 0x280000000-0x2F000000, ANYWHERE fallback)
    # + value-printing markers (d3_val: systrace buf carries addresses)
    # + ctor-stage markers C2-C8 + realpath brackets S1-S3 + operator--
    # guard — fixes the undecodable M02->M03 window.
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v18.hfs
    ROOT_TAG=root-v18
    ROOT_PIN='29360128:331250945df04a7677c78afaee66ab2a6cbcac80d1924b7a759037153507ac33'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT17:-0} = 1 ]]; then
    # root-v17 (D4): root-v16 + D4 dyld (16-retry allocator guard = loud
    # halt instead of silent spin + A1/A2/A3 boottrace markers 0x17-0x19).
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v17.hfs
    ROOT_TAG=root-v17
    ROOT_PIN='29360128:5f82a9016fc76f579937aa036df47a7b3df01b6f4581aad8ba206573c54ac5d9'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT16:-0} = 1 ]]; then
    # root-v16 (D3): root-v15 + rebuilt dyld with bootstrap-correct locks
    # (barrier-only, recursion-count recursive, never-block sync-wait) +
    # the 13-marker boottrace instrument (write(2) length-coded).
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v16.hfs
    ROOT_TAG=root-v16
    ROOT_PIN='29360128:5d62fa4873217fd33a35e5aff3acebd006a3c25c371f4b65609ff54fdc1a9c01'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT15:-0} = 1 ]]; then
    # root-v15 (D2): root-v14 + rebuilt dyld with the syscall-stub LR-restore
    # fix (BSDSYS bl _cerror clobbered x30 -> self-ret EL0 livelock = the
    # v66 exception-vector hang) + munmap 71->73. F1d errno/lock fixes kept.
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v15.hfs
    ROOT_TAG=root-v15
    ROOT_PIN='29360128:89d871b94f0072ab1834990bea12b366986afa8bd3f3aeb063783d696d0dba46'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT14:-0} = 1 ]]; then
    # root-v14 (F1d): root-v13 + rebuilt dyld (TLS-free errno_dyld.c +
    # -DF1D_BOOT_NO_TLS os_lock) — fixes the start() shared-cache-probe
    # cerror/TLS SIGSEGV (errno slot deref at VA 0x8) that killed v65
    # BEFORE prepare(); NXArgcPtr/preferred-load walls still ahead.
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v14.hfs
    ROOT_TAG=root-v14
    ROOT_PIN='29360128:12811844debbd44e49bb39dfe40860c6c59f69fbfd066c2db30f1f9fa4b3f82d'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT13:-0} = 1 ]]; then
    # root-v13 (D1): root-v12 (F1c disjoint compacted dylibs, 16,606 pointer
    # fixes) + PATCHED dyld-1066.8 at /usr/lib/dyld (mapSegments prefers
    # preferred vmaddrs, ANYWHERE fallback) — the two-part fix for the
    # v63/v64 SIGSEGV (swept pointers only valid unslided).
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v13.hfs
    ROOT_TAG=root-v13
    ROOT_PIN='29360128:8559c64349e835966907fdb9ad75bf7b88525a25f62a7cd078282ca468303bd9'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT12:-0} = 1 ]]; then
    # root-v12 (F1c): negative-control profile (compacted dylibs, stock dyld).
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v12.hfs
    ROOT_TAG=root-v12
    ROOT_PIN='29360128:45f3367196e0cbae5b27437024761204715c9fa9657683c8e1592f4adb50d95f'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT11:-0} = 1 ]]; then
    # root-v11 (F1b): root-v10 + 11,757 pointer rebases (per-segment delta,
    # chained-fixup chain-form decoded to clean absolutes) + 380 corrupt
    # sectname repairs — fixes the v63 SIGSEGV (un-applied cache chained
    # fixup at libdyld __dyld4 NXArgcPtr deref'd by dyldMain.cpp:748).
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v11.hfs
    ROOT_TAG=root-v11
    ROOT_PIN='29360128:7106626ecf6bb16c3691686188a9340f9d33e5a87c7eda7c10151bb8d9a7061d'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT10:-0} = 1 ]]; then
    # root-v10 (F1-resume): v8-content base with N1r's repairs actually
    # landed (36/36 export tries, 10,901 exports) PLUS the two defect
    # classes F1 found: 554 stale section fields (vmaddr/fileoff identity)
    # + 31 __got flags 0x0->0x6 — fixes dyld 'indirect symbol has out of
    # range address' (the v61 wall).
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v10.hfs
    ROOT_TAG=root-v10
    ROOT_PIN='29360128:3af78bcb87800967e5e5e21db6a3a84c97bf18da4e68933f0ffbdda4d3b481e6'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT9:-0} = 1 ]]; then
    # root-v9 (N1r): v8 + repaired 36 closure dylibs (real __TEXT restored,
    # LC_DYLD_EXPORTS_TRIE filled from the 20H392 cache tries) so dyld's
    # launchd bind census resolves 537/537 incl. _NDR_record — the exact
    # wall v60 died on ("Symbol not found: _NDR_record").
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v9.hfs
    ROOT_TAG=root-v9
    ROOT_PIN='29360128:a427241dfa71e5088ff1f42695d43018798b64294f53254c001cfb519bba0c17'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT8:-0} = 1 ]]; then
    # root-v8 (Q5): root-v7 + restored carved libdispatch.dylib (the only
    # missing LC_REEXPORT_DYLIB target of libSystem.B) so dyld can load
    # launchd at M2. Same 28 MiB size/window as root-v7.
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v8.hfs
    ROOT_TAG=root-v8
    ROOT_PIN='29360128:77dc3e9f3e2034812112d45cdac2f882c1f7ae3137c432881992d3b4e3d1c0bc'
    MEMSIZE=0x0A400000
elif [[ ${WITH_ROOT7:-0} = 1 ]]; then
    ROOTFS=$ROOT/research/laguna-usb-fix/root-upgrade/root-v7.hfs
    ROOT_TAG=root-v7
    ROOT_PIN='29360128:72bf50b931758a2f2de4b4520a02e4b5177093a820171e82bfcd3878383259ab'
    MEMSIZE=0x0A400000
else
    ROOT_TAG=root-v6
    ROOT_PIN='25165824:aebc9a8a410369b19c60c3e845cb814896bd9709264d2c085283cf816439b4bf'
    MEMSIZE=0x0A000000
fi
printf 'root profile: %s (mem-size=%s)\n' "$ROOT_TAG" "$MEMSIZE"
AVBTOOL="$ROOT/research/native-20261024/reuse/felix-working-source/baremetal_loader/avbtool.py"
KEY=/tmp/test-rsa4096.pem
SALT=666bb996ba0b27623969515f883297de04eaad27d148950c5f24ce0e47c1cc54
ROLLBACK=1791158400
PARTITION_SIZE=67108864

for input in "$R4_MACHO" "$ROOTFS" "$AVBTOOL" "$KEY"; do
    [[ -f $input ]] || { echo "missing required input: $input" >&2; exit 1; }
done
python3 - "$R4_MACHO" "$ROOTFS" "$ROOT_TAG:$ROOT_PIN" <<'PY'
from pathlib import Path
import hashlib, sys
macho, root, pin = (sys.argv[1], sys.argv[2], sys.argv[3])
data = Path(macho).read_bytes()
# 2026-10-27: R5 relocated the evidence channels; the producer magic is now
# XNU-MSGBUF v2 (header at pmsg+0x3F800). Accept v1 or v2 mirror-bearing machs.
if b"XNU-MSGBUF v1" not in data and b"XNU-MSGBUF v2" not in data:
    raise SystemExit("R4 Mach-O lacks XNU-MSGBUF v1/v2; refusing a mirror-less next boot")
root_data = Path(root).read_bytes()
tag, expected = pin.split(":", 1)
expected_size, expected_sha = expected.split(":")
if len(root_data) != int(expected_size) or hashlib.sha256(root_data).hexdigest() != expected_sha:
    raise SystemExit(f"root is not the pinned {tag} bootstrap root "
                     f"({expected_size} B, {expected_sha[:8]}...)")
PY

mkdir -p "$OUT"
if [[ -n ${PROFILE_ADT_PATH:-} ]]; then
    cp "$PROFILE_ADT_PATH" "$OUT/laguna.adt"
else
    python3 "$TL/mkadt.py" "$OUT/laguna.adt" --phys-base=0xd0000000 --mem-size=$MEMSIZE
fi
# v62 (F3, display candidate): io.display.probe=1 io.display.splash=1 added —
# the DC9x00 series (patches-display-foundation 0001..0003) parses these via
# PE_parse_boot_argn; probe defaults 1, splash defaults 0, both set EXPLICITLY
# so the profile is self-describing (Q3 DISPLAY-READY §2.1). splash=2 (the only
# DC-register-write path) deliberately NOT set for the first attempt.
CMDLINE=${PROFILE_CMDLINE:-'debug=0x8 serial=3 cpus=1 io.display.iomfb=1 io.display.probe=1 io.display.splash=1 rd=md0 rootrw=1 ignition_level=1 launchd_unsecure_cache=1 kern.jetsam_critical_threshold=1 interrupt-masked-debug-mode=1 lagunalogdump=1 systrace=1'}
python3 "$TL/mkpayload.py" "$R4_MACHO" "$OUT/laguna.adt" "$OUT/payload-usb.bin" \
    --cmdline "$CMDLINE" --ramdisk "$ROOTFS"
# Opt-in isolated shim source; unset retains the canonical source/output path.
NEXT_BOOT_SHIM_DIR=${NEXT_BOOT_SHIM_DIR:-$TL/shim}
bash "$NEXT_BOOT_SHIM_DIR/build.sh" "$OUT/payload-usb.bin"
cp "$NEXT_BOOT_SHIM_DIR/out/shim-boot-laguna.img" "$OUT/shim-boot-laguna.img"
cp "$OUT/shim-boot-laguna.img" "$OUT/laguna-usb-next-boot-avb.img"
python3 "$AVBTOOL" add_hash_footer --image "$OUT/laguna-usb-next-boot-avb.img" \
    --partition_name boot --partition_size "$PARTITION_SIZE" --salt "$SALT" \
    --algorithm SHA256_RSA4096 --rollback_index "$ROLLBACK" --key "$KEY"
( cd "$OUT" && ln -sfn laguna-usb-next-boot-avb.img boot.img &&
  python3 "$AVBTOOL" verify_image --image boot.img )
shasum -a 256 "$OUT/payload-usb.bin" "$OUT/shim-boot-laguna.img" \
    "$OUT/laguna-usb-next-boot-avb.img" | tee "$OUT/SHA256SUMS"
printf 'Built host-only next-boot candidate: %s\n' "$OUT/laguna-usb-next-boot-avb.img"
