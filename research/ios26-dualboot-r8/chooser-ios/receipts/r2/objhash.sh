#!/bin/bash
# objhash.sh SHIMDIR OUTDIR : ARM64 objects of the chooser units under fixed flags; prints per-section sha256
set -e
D=$1; O=$2; mkdir -p $O
L=~/.local/share/hackios-host/llvm/bin
BASE="-target aarch64-unknown-none-elf -O2 -ffreestanding -nostdlib -fno-pic -mgeneral-regs-only -mstrict-align -fno-stack-protector -fno-jump-tables -w -DTGL_STAMP_NONCE=0x1234ULL -DTGL_UFS_EPOCH=1ULL -DTGL_UFS_RECORD_NONCE={0} -DTGL_UFS_ROUTE=1 -DTGL_UFS_POST_LINK=1 -DTGL_UFS_HANDOFF=1 -DTGL_STAMP_UFS_FOCUS=1"
R13="-DTGL_CHOOSER=1 -DTGL_CHOOSER_MMU=1 -DTGL_CHOOSER_UI=1 -DTGL_CHOOSER_DISPLAY=1 -DTGL_DCS_MENU=1 -DTGL_FRAME_RUNG=3 -DTGL_CHOOSER_KEYS=1 -DTGL_DCS_QUIESCE=1 -DTGL_KEYS_POLL=1 -DTGL_CHOOSER_KEYS_POLL=1 -DTGL_CHOOSER_KEYS_FIX=1 -DTGL_MENU_ROW_HOOK=1 -DTGL_DCS_PRESENT_QUIET=1"
R13D="$R13 -DTGL_CHOOSER_KEYS_DIAG=1"
R12="-DTGL_CHOOSER=1 -DTGL_CHOOSER_MMU=1 -DTGL_CHOOSER_UI=1 -DTGL_CHOOSER_DISPLAY=1 -DTGL_DCS_MENU=1 -DTGL_FRAME_RUNG=3 -DTGL_CHOOSER_KEYS=1 -DTGL_DCS_QUIESCE=1 -DTGL_KEYS_POLL=1 -DTGL_CHOOSER_KEYS_POLL=1"
IOS="-DTGL_UFS_POWER_MODE=1 -DTGL_UFS_PHY_CHECK=1 -DTGL_ALL_STAGES=1 -DTGL_UFS_PWM_FALLBACK=1 -DTGL_UFS_WDT_GUARD=1 -DTGL_ALL_DCS=1 -DTGL_FRAME_RUNG=3 -DTGL_DCS_HANDOFF=1 -DTGL_DCS_BRIGHT=1 -DTGL_FASTCORE=1 -DTGL_CHOOSER=1 -DTGL_CHOOSER_IOS=1 -DTGL_CHOOSER_MMU=1 -DTGL_CHOOSER_UI=1 -DTGL_CHOOSER_DISPLAY=1"
one() { # name src flags
  $L/clang $BASE $3 -c $D/$2 -o $O/$1.o
  for s in .text .rodata .data .bss; do
    $L/llvm-objcopy -O binary -j $s $O/$1.o $O/$1$s 2>/dev/null || true
    printf '%-22s %-8s %s\n' $1 $s "$(sha256sum < $O/$1$s | cut -c1-16) $(stat -c %s $O/$1$s)"
  done
}
one chooser_r13 chooser.c "$R13"
one chooser_r13diag chooser.c "$R13D"
one chooser_r12 chooser.c "$R12"
one cios_r1ios chooser_ios.c "$IOS -DTGL_CHOOSER_IOS_DEFAULT=1"
one cios_r1 chooser_ios.c "$IOS"
one cios_r0keys chooser_ios.c "$IOS -DTGL_KEYS_POLL=1"
one dcsm_r1 tgl_dcs_menu.c "$IOS"
one menu_ui_r1 menu_ui.c "$IOS"
