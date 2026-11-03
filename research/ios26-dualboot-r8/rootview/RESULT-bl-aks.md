# kernel.rootview-bl-aks: kernel.rootview-bl + AKS wrap/unwrap (HOST build, 2026-11-03 16:39)

Not booted anywhere (no QEMU, no phone). For boot B1 of `research/ios26-connectivity-r1/bluetooth/PLAN.md` §5.

- Source: release tree `research/ios26-release-r1/work/xnu`, new branch **`hk-aks-wrap`**, commit **44689e02f105f2daea3dae5762912d6847f81902**
  = `hk-bright-calib-bl` f24a98d + `aks-wrap/0001-sweet-aks-wrap-unwrap.patch` (02803352…) and `0002-blazer-aks-wrap-build-on.patch`
  (a45358fd…) applied unchanged with `git apply` (SweetKeyStore.cpp +146, new blazer_aks_wrap.inc +212, MakeInc.def 1 line).
- Build: `research/ios26-release-r1/tools/mk.sh -j8` (same flags/OBJROOT as kernel.rootview-bl) under an fcntl lock of
  /tmp/fleet/kernel-build-slot.lock, script `aks-build/build_aks.py`, output `aks-build/build_aks.out`. rc 0, 76 s. The MakeInc.def change
  made it a full rebuild (1087 compiles, `aks-build/aks-wrap-build.log`); only SweetKeyStore.cpp tests BLAZER_AKS_WRAP.
  The tree was on `p1` (b228c4f), clean, no build running; it was switched back to `p1` and rebuilt (rc 0, full,
  `aks-build/aks-wrap-restore-p1-build.log`; obj kernel 53694bcb…, link not reproducible).
- Mach-O 64-bit arm64, UUID BBB9B8A9-93EB-3C5D-98A8-BC1487ACB5EF. Stripped and unstripped: `_cchmac`, `_ccsha256_ltc_di`, `_read_random`
  defined (S); `SWEET AKS: wrap/unwrap on (software, per-boot secret, system bag only)` and `SWEET AKS: %s refused: %s` once each.
  Disassembly: `sweet_aks_hmac` = `x0 = &_ccsha256_ltc_di; b _cchmac`; `AppleKeyStore::start` calls `PE_parse_boot_argn`, `read_random`,
  `_cchmac` x2; `externalMethod` has `cmp w22, #0xa` x2 and calls `aw_tag`/`aw_xor` x2 each.
- Diff vs kernel.rootview-bl (unstripped, `aks-build/symdiff.py`, `aks-build/symdiff.txt`): no symbol removed; added only
  `sweet_aks_hmac`, `aw_tag`, `aw_xor` (text), `sweet_aks_wrap` (bss), `aw_status_name::names`, `aw_init` enc/mac labels; size changes only
  `AppleKeyStore::start` 128 → 496 and `AppleKeyStoreUserClient::externalMethod` 944 → 3088. All from SweetKeyStore.cpp.
  `size -m` (`aks-build/size-diff.txt`): __TEXT_EXEC grows one page (+16384), so every later segment shifts by 0x4000.
- Image `research/images/a7-ios-system-b1-aks` = a7-ios-system-r5-accel's recipe (A7-READY step 6, accel-skip overlay f5d4c367…,
  hk_bright=140, 5 cores, bootcpu 0x200, deadline 300) with this kernel. `image_tool.py check` OK. Cmdline diff vs r5-accel:
  `-hk_present_trace=1 +blazer_aks_wrap=1`, token order otherwise identical, 1013 → 1012 bytes (keeping hk_present_trace would be 1030 > 1023).
  Other manifest changes are layout only (segments, plan, overlay placement +0x4000) and the per-build ADT seed/ids.
  Needs `tools/image_tool.py` with `aks-wrap/image_tool-aks-wrap.patch` (applied on the Mac with git apply on top of the owner's
  uncommitted hunk: 56a015a0… → b56ae2bd…).
- Pass criteria for the boot (PLAN.md §5 B1): `SWEET AKS: wrap/unwrap on` once; `securityd sel 10 … -> 0x0` and no sel 10 `-> 0xe00002c7`
  (r3: 33); no `wrap refused`/`unwrap refused`; no new usertraps; Home, touch, Settings as before; Android return check PASS.

9e08c2b62744f3db31a22ee8fefce342b097bf6b1ae9204395e1e6aec470562b  ios26-dualboot-r8/rootview/kernel.rootview-bl-aks
e0c6302b690c55c4abd855647d79f65b9ab27f515c788a5fbb10dae14df9ca5b  ios26-dualboot-r8/rootview/kernel.rootview-bl-aks.unstripped
c6b84fef58e327b774560f33acf8de12b236d8def9b1e2ed3acbc50e872ac5e0  images/a7-ios-system-b1-aks/boot.img
