# QEMU A/B intent (written 2026-11-03 20:15, before the runs)

Question: in QEMU, does configd's InterfaceNamer leave SCNetworkInterfaceCopyAll waiting (A), and does blazer_netstack=1 make it
answer (B)? One variable: `blazer_netstack=1`.

- Rig: m1box `/data/hackios-qemu`, `research/ios26-apps-r1/tools/qemu-ufsroot.py`, TCG, 1 CPU, `--window-gib 28`, runtime/idle 900 s.
- Kernel (both): `kernel.rootview-bl-aks-us2-ns1` f75a20c47dc978b8958bb359adf21ba143453fa567328af2ab4597a0f5ca5967 (hk-netstack-cfg1 093ca86).
- Root (both): `artifacts/apps-logmirror-r14.img` (the root of r25/app2-r26), read-only.
- Overlay (both): `qemu-cfg1-scwait.ovl` 7acd3d4a... = perf-r1.ovl + hk_scwait in powerd (QEMU only).
- Args (both): runq.sh TAIL (blazer_deadline=1800, hk_overlay=0xA0080081 ...) + `blazer_persona_log=1 blazer_aks_wrap=1 blazer_aks_usersession=1`
  (r25's). B adds `blazer_netstack=1`.
- Decisive console lines:
  - A expected: `HKSC: t=... keys=none` (or no *QUIET*/*COMPLETE*) and `still waiting` until about configd start + 300 s, then
    `keys=...*TIMEOUT*` and `SCNetworkInterfaceCopyAll returned after ~300+ s`. No `blazer-netstack:` lines.
  - B expected: `blazer-netstack: published alone`, `blazer-netstack: IONetworkStack opened by configd[N] ... busy B`, then
    `HKSC: ... keys=*STACK*,*QUIET*...*COMPLETE*` and `SCNetworkInterfaceCopyAll returned after` seconds, not minutes.
    If busy B > 0: the busy-leaf lines and the `IOKit quiet ... ms` line say when.
- Either result is recorded. QEMU results are QEMU results: the phone's IOKit busy state can differ.
