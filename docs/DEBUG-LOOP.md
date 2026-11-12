# The fast debug loop: end a boot when the evidence is in

A boot no longer has to run to `blazer_deadline` (900-1800 s). With **`blazer_usbcon=2`** in the image, the host can
end it on purpose: usbcon request 0x5c makes the kernel panic with "blazer-usbcon: the host asked to end this boot".
That runs the normal panic path: warm reset, then a park in fastboot (force-fastboot is armed by the boot tools), so
RAM survives for the ramdump. Mode 1 kernels stall 0x5c, so nothing happens. The deadline is still the fallback.

**The one token change.** In the image recipe's boot arguments, replace `blazer_usbcon=1` with `blazer_usbcon=2`. Example:
`BASE_ARGS` in `research/ios26-phaseb-r1/knext/tools/mkimg_knext_ios_r1.sh`, or `ARGS` in `int4/tools/mkimg_int4.sh`.
Then rebuild that image. `tools/image_tool.py`'s `PHONE_ALLOWED` (`blazer_usbcon=[12]`), every forked `image_tool_*.py`
and `--cpu-audit` admit it. Three exceptions keep mode 1: `--cpu-health`, whose line is frozen and pinned;
`blazer_usb_readback`, which is read-only by design; and `hk_dbg`, which has no mode bit.

## The loop

    hk state                                   # android | fastboot | ios-live | shim | recovery | absent, with how it knows
    hk to-fastboot --lock me                   # from anything that answers; see below
    hk cycle IMAGE --mach K --lock me --end-on 'REGEX' [--end-grace S] [--end-after S] [--end-on-idle S]
    hk status / hk crash / cycle/report.md     # the report says which condition ended the boot

`hk to-fastboot` does one of the following, depending on the state:
- **android**: runs `adb reboot bootloader`.
- **ios-live** with a running reader (a fresh live run's `LIVE_SOCK`): sends the `reset` op through the reader.
- **ios-live** with no reader: starts a short reader (`usbcon.py --reset-after 0`) that sends the reset.
- **fastboot**: does nothing.
- **shim** (1209:0001): asks you to wait 10-30 s and run it again.
- **recovery**: the owner picks "Reboot to bootloader".
- **absent**: the owner holds power + volume-down. That is a **cold** reset, and the ramdump is lost.

If a mode-1 boot refuses the reset, the command says so and changes nothing (exit 6, `reset_not_armed`).

`hk_cycle --end-*` conditions (the first to fire sends the reset once, then park, ramdump and analysis run as usual):
- `--end-on REGEX`: the first live console line that matches, plus `--end-grace S` (default 5 s) for trailing lines.
- `--end-after S`: S seconds after Home (`UI_READY`, or exec SpringBoard + touch + buttons + frames).
- `--end-on-idle S`: S seconds with no kernel console line. The reader's own `usbcon:` lines don't count.

Preflight refuses `--end-*` on a mode-1 image (`END_NEEDS_USBCON2`) before it touches the phone. If the reset is refused or
unclear, the report records an error (`END_RESET_*`), nothing is sent again, and the deadline ends the boot.
`report.json` and `summary.json` record `end` as one of `end-on`, `end-after`, `end-on-idle` (with the line or the time), or
`deadline`, `panic`, `host-end` or `unknown` (read from the console).

You can also send the reset by hand to a running reader: `python3 -I tools/usbcon.py --control-socket SOCK --reset-now`
(run on the Mac, with `mac repo --force --`). `hk_boot_job.sh` does the same from `HK_END_ON=REGEX` or `HK_END_AFTER=S`.

## Worked example: boot, wait for the Wi-Fi join line, end, next image

    hk state                                                    # -> android  (`adb devices` lists it as device)
    hk to-fastboot --lock me                                    # -> android -> fastboot by adb reboot bootloader
    hk cycle a7-wifi-join-r6 --mach research/.../kernel.wifi.unstripped --lock me \
        --end-on 'blazer-wifi: join: joined' --end-grace 20 -- --no-return-check
    #   ... "end-on: matched at +212 s: blazer-wifi: join: joined"; 20 s later the reset op, park, ramdump, report
    #   report.md: "Ended by: **end-on** (matched 'blazer-wifi: join: joined': ...) at +232 s, reset reset"
    hk cycle a7-wifi-join-r7 --mach ... --lock me --end-on 'blazer-wifi: join: joined' --end-grace 20

Each cycle still returns the phone to Android (`fastboot reboot`, about 2 min). `-- --no-return-check` skips only the
read-only return check. If a cycle is interrupted and the phone is left in iOS, run `hk to-fastboot` first.
The `wifi` row in `docs/probes.yaml` lists the other Wi-Fi lines worth ending on, for example the gateway ping.

## A queue of boots: `tools/hk_session.py` (the phone stays in fastboot between boots)

    python3 -I tools/hk_session.py /data/work/hk-fleet/queue --results /data/work/hk-fleet/results --check   # validate only
    python3 -I tools/hk_session.py /data/work/hk-fleet/queue --results /data/work/hk-fleet/results --stay    # run; end parked
    python3 -I tools/hk_session.py /data/work/hk-fleet/queue --results /data/work/hk-fleet/results           # run; then Android
    python3 -I tools/hk_session.py --return --results /data/work/hk-fleet/results                            # only: back to Android

Per `.req` (oldest first): preflight, to-fastboot from any state (a running iOS boot is ended by the reset op), `hk_cycle
--stay-fastboot` with the request's END_ON / END_AFTER / ABORT_ON (neither END: 90 s after Home), and when the end condition
fires: the QUERIES through `tools/hkq.py batch`, one screenshot, the reset, the park, the ramdump; then `hk_score` with
`--diff`/`--baseline /data/work/hk-score/baseline.json`; then `<results>/<req>/REPORT.md`; the finished `.req` moves to
`queue/done/`. ABORT_ON ends at once (no grace, no queries). A request refused for its own reasons does not stop the queue; a
failure of the surroundings does, and that request stays pending. The last line is always `hk_session: phone: STATE (how)`.

**Mac-side tools.** `tools/mactools.py ensure` copies m1box's bootios, usbcon.py, hkq.py, capture-fastboot.py and usb_log.py to
`~/.cache/hackios-tools/<id>/` on the Mac (id = hash of the files), verifies each by sha256 and prints the directory.
live_boot.sh, hk_cycle, hk, screenshot.sh and the UI runners run the tools from there (`LIVE_TOOLS` in live.env); the Mac
checkout's own `tools/` are never run or overwritten, so a checkout on another commit no longer refuses a boot. Clients of
the reader's socket (UI steps, screenshots, hkq, reset) take `<live run>/.reader.lock`, one at a time.

**The way back to Android.** Never `fastboot reboot` while force-fastboot reads on: it only parks again and adb never comes
(`hk_boot_job.sh` did that on 2026-11-11). The return turns it off, reads it back, and then
- `--return-via stock` (hk_session's default): `fastboot boot research/ios26-dualboot-r8/truth/boot_b.img` (sha256 checked),
  a temporary boot of stock Android that passes the installed chooser by; or
- `--return-via chooser`: `fastboot reboot` into the installed boot_b (menu, Android after 5 s).
The wait then names what it sees and sends nothing more: fastboot again (one more try, then it stays there), an iOS gadget
(the chooser started iOS: waited to its deadline), or no USB at all (the installed chooser is built without USB; waited up to
20 min). The return check records `bootreason` and the kernel base (0x80000000 stock boot, 0xc9c00000 chained by the chooser).

**Vendor requests.** `usbcon.py`'s `vendor` op carries exactly what the kernel serves: 0x70 (hk_ustack, 56 bytes) and
0x71..0x73 (hk_query, 96 bytes), device-to-host. One EP0 reply of this gadget is at most 384 bytes and there is no OUT data
stage; anything bigger comes over the console (hkq: up to 48 KiB per query).
