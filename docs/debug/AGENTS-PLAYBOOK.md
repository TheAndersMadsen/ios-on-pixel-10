# Agents playbook: many debuggers, one phone

How parallel LLM agents claim work, share the phone, and record results. Tool reference: `tools/hk --help`,
`research/ios26-phaseb-r1/hub/HUB.md`. Subsystem map: `docs/debug/MAP.md`. Policy above all of this:
`docs/COORDINATION.md`, which still applies (the phone owner admits physical tests; only coordination commits).

## 1. Claim a subsystem

- One accountable owner per scope. Claim it in your thread's first message with the MAP id: `CLAIM wifi (agent W3): …`.
  The coordinator records claims; `hk find --feature wifi` shows the subsystem's attempt history before you start.
- Read the MAP block (`grep -A12 '^SUBSYS: wifi' docs/debug/MAP.md`) and the docs it links. Do not crawl research/.
- Work in your own scope. Wrap other agents' tools; propose interface changes to their owner (HUB.md section 4).

## 2. The order of evidence (cheapest first, fewest reboots)

1. **Existing dumps**: `hk find`, `hk logs`, `hk crash`, `hk stacks`, `hk report` on attempts already in the store.
   `hk ingest --all` imports every older runner run. Most questions are answered here without a boot.
2. **Host**: unit tests, ARM64 objects with the feature gates enabled and their symbols inspected (AGENTS.md).
3. **QEMU**: `hk qemu research/images/X` (TCG on m1box; its own slot lock). QEMU results are QEMU results.
4. **Live, no reboot** (a boot that is already running, with DBG1's net and DBG2's shell in its image):
   `hk shell`, `hk stacks PROC --live`, `hk push` + `hk restart` to hot-patch a dylib in /private/var, `hk shot`, `hk ui`.
   Ask the current lease holder first: their boot, their run.
5. **A new boot**: `hk queue add IMAGE [UI] [EXPECT]`. Batch several questions into one image (several MAP probes,
   several `hk_ustack` names, several HKL mirrors) instead of one boot per question.

## 3. The phone lease (one owner of the device and usbcon)

- `hk lock status` shows the holder, purpose and expiry. A lease expires; a pid-bound lease (taken by a running `hk boot` /
  `hk cycle`) is also stale once its process is gone. `hk` reclaims expired or stale leases and logs the event
  (`/tmp/fleet/hk-phone.events.jsonl`).
- Every phone-changing command (`hk boot`, `hk live`, `hk cycle`, `hk back`, `hk ui`, `hk push`, `hk restart`) REFUSES with
  exit 4 `lock_required` unless you name yourself: `--lock NAME` or `HK_LOCK=NAME` (lease held by NAME: inherited and left
  held; phone free: taken for that command only, released after), or `HK_LOCK_TOKEN`. Someone else holding it: exit 4
  `phone_busy` naming the holder. `--lock-wait S` waits.
- Several steps in a row (a cycle, then `hk ui`, then `hk back`; attended key presses): `hk lock acquire NAME --purpose
  "owner keys test" --ttl 1800`, `export HK_LOCK=NAME`, run them, `hk lock release NAME`. `hk lock check [NAME]` exits 0
  only for the holder (for scripts). An expired lease is broken by the next `acquire`, with a note in the events file.
- `hk lock break --force --reason …` only on the phone owner's or coordinator's word. Never edit the lease file by hand.
- Read-only commands need no lease: `hk status`, `hk probe`, `hk state`, `hk find`, `hk logs`, `hk crash`, `hk stacks` (from a dump), `hk report`,
  `hk images`, `hk shot` (asks the running reader; it never opens USB), `hk shell` for reading (logged in
  `attempts/shell.jsonl`). Do not run state-changing commands through `hk shell` without the lease.

## 4. The queue (one runner serialises phone use)

```
hk queue add research/images/a7-ios-system-obs1 ui/settings_about_phone.ui expect/int1.yaml --mach K.unstripped --note "wifi + about"
hk queue list                     # pending, NOT-ADMITTED until the phone owner admits it
hk queue admit <qid>              # phone owner / coordinator only (COORDINATION.md: fresh binding review)
hk queue run --follow             # the ONE runner; takes the lease per item, runs hk cycle, records the attempt
hk queue show <qid>               # attempt id, verdict, return check
```

- Only admitted items run. No unchanged retries: a FAIL is recorded, not requeued. A busy phone puts the item back.
- `--mode cycle` (default: hk_cycle, which includes the return to Android) or `--mode boot` (live_boot, then `hk back`).

## 5. Record results

- Every boot is `attempts/<id>/` (manifest.json, runner/ ramdump/ live/ console.txt, screens/, crashes/, probes/, logs/,
  return/) plus one line in `attempts/index.jsonl`. `hk note <id> "owner pressed Vol Down at 12:03"` records owner actions.
- `hk report <id>` writes REPORT.md. Put your conclusion in your own research directory with the attempt id, and one LEDGER
  line (time, lane, run id, the one variable, result, next variable). Label evidence classes. Hand the commit request
  (paths, hashes, message, NOTES text) to coordination; never stage or commit.

## 6. Lessons from 2026-11-03 (do not relearn them)

- **stdin**: commands through `mac`/ssh get no usable stdin (the bridge feeds a watcher pipe), and a child that reads stdin
  can eat a loop's input. `hk` runs every child with stdin from /dev/null and sends shell input as arguments.
- **Cold reset**: never cold-reset (power + volume down) a running iOS boot: RAM, and so the ramdump, is lost. Every boot ends
  at its own `blazer_deadline` and parks in fastboot (force-fastboot on). A real power-on goes through the installed menu on
  boot_b; a cold power-on leaves USB unpowered (the r2 usb-warm fault, fixed by `--cold-safe`). `fastboot boot` tests do not
  reproduce cold-start behaviour.
- **`--force`**: `mac repo` refuses when m1box and the Mac are on different commits; `--force` skips that. Use it only for the
  read-only console reader (as live_boot.sh does), never to push a boot of code the Mac does not have. Sync tools
  explicitly (`--sync-tools`) and record both revisions.
- **Single usbcon reader**: one EP0 console reader per Mac (flock `/tmp/hackios-usbcon-UID.lock`). Input, snapshots and
  stack requests go through the reader's control socket (`LIVE_SOCK` in live.env). A second reader, or `ustack_ctl.py`
  while a reader runs, is refused. The phone lease covers usbcon too.
- **Never pkill your own shell**: `pkill -f usbcon` matches your own command line (and the agent's shell). Stop only the
  process group you started (hk does: own session, `killpg`), or a pid you recorded.
- **Disks by name**: LUN letters change between boots (sda then sdb); resolve partitions by `/dev/block/by-name`.
- **Stale screen records**: a ramdump keeps older boots' residue; fb_png refuses a record whose XNUENT1 identity is not this
  boot's. Do not pass `--allow-stale` to make a picture appear.
- **Build mtimes**: `shutil.copy2` keeps an old mtime and make skips the file; copy plainly and touch, then check the kernel
  for the new strings before booting.

## 7. Shortest loops per layer

| Layer | Edit | Check without a boot | Live, no reboot | Needs a boot |
| --- | --- | --- | --- | --- |
| userland daemon behaviour | overlay hk_env row, dylib | QEMU (`hk qemu`) | `hk push` dylib + `hk restart DAEMON` (DBG2) | new overlay in a phone image |
| daemon logs | HKL mirror rule | QEMU | `hk logs PROC --live` | mirror rule change |
| app UI | ui script | `hk ui SCRIPT --check` | `hk ui SCRIPT` | — |
| kernel driver | xnu source | ARM64 objects + symbols, QEMU if not Tensor hardware | boot-arg-only changes need a boot | always |
| shim / chooser | shim source | host tests (`shim/*_test.c`), image check | — | always (`fastboot boot`) |

## The backlog

`docs/debug/BACKLOG.md` (+ `backlog.json`) is the live, assignable issue list, generated by `tools/backlog.py ATTEMPT_DIR...` from probe_eval + crashdoc, merged with `backlog-notes.json`. Regenerate after each boot. UNASSIGNED items are ready to spawn an agent against; owners map to the current fleet lanes.
