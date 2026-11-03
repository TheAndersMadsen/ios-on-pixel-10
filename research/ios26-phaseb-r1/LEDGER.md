# Phase B ledger (m1box rig, /data/hackios-qemu)

One line per run: time (CET), lane, run id, the one variable, result, next variable. QEMU results are QEMU results.

| Time | Lane | Run | One variable | Result | Next variable |
| --- | --- | --- | --- | --- | --- |
| 12:21 | rig | cal-r12d-kvm | accel kvm (else = Mac r12d intent) | KVM does not boot: last console line "EARLY 8: leaving bootstrap console mapping"; all PCs in fleh_synchronous_sp1/_el1_sp1_synchronous_vector_long_invalid_kstack, x1 0x96000006 (data abort, L2 translation fault) | none: loop runs on TCG |
| 12:22 | rig | cal-r12d-tcg | none (Mac r12d intent on m1box TCG) | boots (4212 console lines) but cut at 120 s by --idle 120 (uart.log always empty here) | --idle 0, --runtime 420 (cal-r12d-tcg-b) |
| 12:27 | rig | cal-r12d-tcg-b | --idle 0, 420 s | TCG equivalent to Mac r12d: same 18 early milestones and first 20 launchd subjects in order, 10/50 boot tasks, no panic; faster (launchd 1.8 s vs 5.0 s). receipts/m1box-rig/CALIBRATION.md | loop on TCG |
| 12:33 | 4 | registration-logmirror-r14 | os_log mirror for lsd + usermanagerd (r13 otherwise: rd=ufsroot0, kernel.rootview, apps-full-r6) | lsd: `container lookup query: 3b(76) INVALID_PERSONA` -> `Could not get user container URL! Must abort.`; usermanagerd daemon: `no personas found for user D386B5CD-…`, `getUserSessionKeybagData: could not find the requested session`; UMD_INIT ran (boot task) | why --init leaves no personas: its own os_log, then persistence |
| 12:40 | 1 | (static) | backboardd NSURL-nil abort, phone captures, dsc_dis | root cause: BaseBoard BSSystemSharedDirectoryForIdentifier -> container_system_path_for_identifier() NULL -> nil -> -[NSURL initFileURLWithPath:] throws; QEMU consoles show 0 backboardd aborts (r12d, r13, cal) | QEMU reproduction or fix run |
| 12:52 | dual boot | chooser-v1-r10-t1 (PHYSICAL) | stock vs_drm.ko DPU quiesce before the release | FAIL: quiesce complete (Q_L0_ST 0x18, Q_BE_DBG 0, Q_ISO 0xf), then CPM Assert lpb.c:676 sswrp_id < LPB_NUM_SSWRPS on LPCM FE0 off (same as r9); return PASS | LPCM off frame field order |
| 12:59 | dual boot | chooser-v1-r11-t1 (PHYSICAL) | LPCM off frames per vendor send_lpcm_mail (REQ_ID 7:0, ON 31:24): 0x00000001 / 0x00020001 | PASS: Android after the display path in 42 s, kernel 0xc9c00000, return PASS; menu on panel awaits owner confirmation | owner confirms menu; keys (r8 line) |
| 12:58 | 4 | registration-nopersonakb-r15 | remove seeded var.skel persona.kb | VOID: file removed but varfs seed list kept it; seeder panic at 184 ms (my edit error) | same variable done fully (r15b) |
| 13:08 | 4 | registration-nopersonakb-r15b | no seeded persona.kb (file + var.skel.tsv line) | running | per intent-r15 discriminators |
