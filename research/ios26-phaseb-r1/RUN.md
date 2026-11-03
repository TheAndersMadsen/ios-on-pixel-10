# Phase B run on m1box (brief for the owner thread; read with GOAL.md)

Written 2026-11-03 12:10 CET by the Mac thread at the owner's direction. GOAL.md stays the authority (sections 2, 3, 7,
8, 9, 10). This file only says what this run must produce and how to use the m1box rig. Copy it to
`research/ios26-phaseb-r1/RUN.md` and commit it as the first action of the run.

## State at the start

- Phase A unattended stages are complete (311f4fa, 69b84d7). r10 (display handback, one attended `fastboot boot`)
  and A7 (first `ios_system` flash) wait for the owner: keep their paste-ready commands current in
  `research/ios26-dualboot-r8/NEEDS-OWNER.md`; never run them; the phone is on the Mac.
- Android is verified on the phone (`attempts/return-after-restore/` PASS). Do not touch it.
- The QEMU rig on m1box is ready: `/data/hackios-qemu/README.md`. Run every QEMU experiment there. Do not run QEMU
  through `onmac`; the Mac's disk and single slot were the bottleneck of the last 24 hours.
- Lane 4 (apps/H3) so far: with `rd=md0` launchd skips its boot tasks (usermanagerd among them). r12d was
  INCONCLUSIVE (the added job never loaded). r13 (`registration-ufsroute-r13`, UFS route, root `apps-full-r6.img`,
  600 s on the Mac, exit 0) ran 58 boot tasks including `usermanagerd` (`IN UMD_INIT` / `DONE UMD_INIT`), with zero
  `Unable to find persona` lines, but no `Created mobile user` / `Allocated kernel persona` either, and `lsd` now
  dies with `userabort: lsd[...] aborts` (backtrace in the console) instead of refusing registrations. Record r13
  yourself from `runs/registration-ufsroute-r13/` (on the Mac; copy the run directory to m1box first). The next
  one-variable test is that abort: symbolicate the backtrace against the shared cache slide, name the frame, then
  one change. Both roots are on m1box: `artifacts/apps-umdinit-r12.img` and `artifacts/apps-full-r6.img`.

## Deliverables (all of them; this is what "done" means for this run)

1. **Rig adopted.** `/data/hackios-qemu/research/ios26-apps-r1/tools/qemu-ufsroot.py`, `mkvariant.sh`,
   `sync-variant.sh` and `README.md` committed under `research/ios26-apps-r1/tools/m1box/`. Calibration receipt
   `research/ios26-apps-r1/receipts/m1box-rig/CALIBRATION.md`: for `runs/cal-r12d-tcg` and `runs/cal-r12d-kvm`
   versus the Mac's `registration-umdinit-r12d`: time to the first launchd line, the first 20 distinct console
   milestones in order, the count of `Unable to find persona` lines at 300 s, and the verdict "KVM equivalent / KVM
   differs in X / KVM does not boot (first exception line)". Use KVM for the loop only if the verdict is "equivalent".
2. **Lane 4, H3.** A run in which the user-session creator demonstrably executes (its own console line), then H3
   confirmed or rejected by the discriminators in `receipts/h3-static-r12/intent-r12.json`; or two materially
   different failed hypotheses recorded (GOAL.md section 7 stop rule). If confirmed: a container app registered by
   lsd in QEMU is the acceptance.
3. **Lane 1, compositor.** The early `backboardd` NSURL-nil abort root-caused from the disassembly (the frame, the
   nil argument, what fills it on a real device), one QEMU run with the fix, measured as backboardd respawn count
   over 15 minutes; or two failed hypotheses recorded. Also the CoreBrightness Q16.16 lead if a run slot is idle.
4. **Lane 2, negative test.** XNU dd000c8 (ios_data persist) in QEMU: a run that proves it writes nothing outside
   `ios_data` (the HANDOFF item), receipt under `research/ios26-dualboot-r8/ios-data-persist/`.
5. **Ledger.** `research/ios26-phaseb-r1/LEDGER.md`, one line per run: time, lane, run id, the one variable, result,
   next variable. It must gain a line at least every 45 minutes of wall clock while a run is possible; if nothing can
   run, the line says why. No run without an intent file written first; no result without the console line that decides it.
6. `NOTES.md` current-state lines and `HANDOFF.md` next actions replaced; everything committed on `ios26`; no push.

## How to work

- Concurrency: `HACKIOS_QEMU_SLOTS=3` (TCG, one core per guest) or more under KVM if calibrated. Lanes 1, 2 and 4 run
  side by side. Build variants on m1box with `mkvariant.sh`; pull Mac-built ones with `sync-variant.sh`.
- Helpers: at most four, host-only, short-lived, each with one deliverable (a disassembly trace, a plist or launchd
  cache diff, a test). They never touch QEMU, git or the phone. Verify what they return against the raw file.
- Budget: run to the budget. Stop a lane after the section-7 rule, then move to the next lane in order.
- Never claim a feature works without the acceptance evidence GOAL.md names. QEMU results are QEMU results.
