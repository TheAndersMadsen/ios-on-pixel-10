# QEMU receipts (m1box rig, TCG). QEMU evidence only: QEMU has no CPM mailbox and no S5400.

| Run | Kernel / line | Result |
| --- | --- | --- |
| `qf-modem1-stage4` (300 s) | kernel.modem1 159898f6; pre-flight's harness args + `hk_dbg=0x4000000` | 0 panics; `blazer-modem: stage 4 (link) … starts in 30 s`, `stopped: mailbox magic, detail 0x0`, `verdict: STOP stage 4, at none: mailbox magic, … frames 0`; launchd, backboardd, SpringBoard exec after it. `qemu-stage4.txt` |
| `qf-modem1-off` (600 s, `tools/qemu_preflight.py`) | a7-ios-system-modem1, `hk_dbg` dropped by the pre-flight (modem off, 0 `blazer-modem` lines) | every milestone OK incl. Home equivalent (353 s), no panic, 7/7 int3 expect rows PASS. Verdict FAIL on two crash-loop rules: fairplayd.H2 32x, datamigrator 5x; int3's own `qf-int3-r2` has the same (39x, 5x). `qf-modem1-off.txt` |
| same, `--baseline qf-int3-r2` | | adds "missing vs baseline": passd (a false miss: its `exec passd` line is glued to a previous console line, line 1380), UserFontManager and wcd (on-demand; int3 launched them late, lines 2610/3026 of 3654). The modem code did not execute in this run, so this is not attributed to it. `qf-modem1-off-vs-int3.txt` |

Conclusion: the modem ladder compiled into int3 is inert when off. When on and the hardware is absent it stops before its first frame without a panic.
Nothing here says anything about the phone's modem.
