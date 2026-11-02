# Contributing

This is a private research bring-up on the owner's own Pixel 10 Pro. Read [`AGENTS.md`](AGENTS.md) and [`NOTES.md`](NOTES.md) first: they hold the current state and the working rules. Work goes on branch `ios26`; `ios16` is frozen.

## Setting up

```sh
git config core.hooksPath .githooks   # runs the tracked-file check before each commit
.github/scripts/ci-tests.sh           # host tests, no phone
```

A clean clone can run the tests above, but can't build an image. [`docs/BUILD.md`](docs/BUILD.md) lists the local inputs.

## How boots are run

1. **Ask first.** The owner decides whether boots may run, and one person starts them. One boot at a time.
2. **Test on the host before spending a boot.** Run a QEMU guest where one can answer the question. For blazer XNU code, turn on the feature gate being tested, emit ARM64 objects and inspect the expected symbols: a guarded file can compile to nothing, so syntax-only success proves nothing.
3. **Build a new image under a new name.** An image is never rebuilt: `python3 -I tools/image_tool.py image NAME ...`, then `check`. Each input is pinned by hash.
4. **Boot only with `tools/bootios`.** It runs `fastboot boot`, which loads the image into RAM. It also sets `force-fastboot` on and leaves it on, so the phone returns to fastboot, where the diagnostics are read.
5. **Keep within the limits.** Each boot has a deadline, and a voted clock on a UI boot needs the armed thermal guard. After a run of 15 minutes or more, rest the phone for 15 minutes.
6. **Read the result.** Use `tools/boot-summary.py <attempt>` for how a boot ended, plus the test's own reader. `kernel.log` is a RAM ring, so lines from an earlier boot can survive in it: trust a line only if the summary binds that log to this boot.
7. **Record it.** Put the attempt name, image and kernel hash, boot line, exact result, and what was observed against what was guessed, in `NOTES.md`. Update `docs/status.json` when a feature's state changes.

## Safety rules

The phone has to stay recoverable, and Android has to stay intact.

- **Each destructive step is confirmed by the owner immediately before it runs.** An earlier approval doesn't carry over to the next step. That covers any write to a partition, including another root write to `userdata_exp.ai`, and anything else that can't be undone.
- **Leave alone:** bootloaders, slots, firmware, Android's partitions and data, and the partition backups. No `flash`, `erase`, `format`, `set_active` or slot change.
- **No voltage changes, gauge or touch firmware updates, Titan writes or TRIM.**
- **No first read of an unpowered block.** A guarded read of an unvoted peripheral has caused a later reset, and a fault guard doesn't make such a read safe.
- **Stop on the unexpected.** Heat over the limit, a capture that doesn't fit, or a reset nobody can explain: stop and report it.

## Never commit

- Device dumps: images, `ramdump/`, `kernel.log`, device trees, partition backups
- Serial numbers, IMEIs, MAC addresses, account names, or photos and screenshots showing them
- Apple's files: kernelcaches, shared caches, root filesystems, Device Trees, IPSWs, iOS screenshots
- Firmware from any vendor, and keys, including the test keys
- Anything under `research/`, including the kernel series. Its context lines are tegu's, which has no licence
- Third-party code with no entry in [`docs/LICENSING.md`](docs/LICENSING.md)

`.github/scripts/check_tracked.py` looks for these by file name and by a few number patterns, in CI and in the hook. It's a net, not an audit: you remain responsible for what you add. If something slips into a commit, tell the owner rather than deleting it quietly, because it stays in history and must be rewritten out.

## Commits and pull requests

Commit completed changes, one purpose at a time, with a subject that says what changed. Fill in the pull request template. Report results as they were, including failures and skipped steps.

Issues use the templates: a boot report takes the attempt's name.
