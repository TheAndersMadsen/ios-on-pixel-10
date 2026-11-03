# Phone test: modem rungs 1..4 in one unattended boot (a7-ios-system-modem1)

**Not run.** The coordinator boots; this lane never touches the phone. Pre-approved class: a temporary `fastboot boot`
(no flash, no partition write, slot unchanged). One boot answers all four rungs, because each stage stops at its own named
failure and puts back what it drove.

## What the image is

- `research/images/a7-ios-system-modem1` = `a7-ios-system-int3` byte for byte except
  - kernel `research/ios26-modem-r1/build/kernel.modem1` (XNU `hk-modem1` = hk-int3 3dc7fec + `xnu-src/0001-hk-modem1.patch`),
  - boot line `hk_dbg=0x1e1e1f` → `hk_dbg=0x41e1e1f` (bits 24..27 = 4: modem stage 4, no hold). 1000 → 1001 bytes.
- Built by `tools/mkimg_modem1.sh KERNEL_SHA256` with the copied tool `tools/image_tool_modem1.py`. Hashes in `receipts/SHA256SUMS.image`.

## What it does on the phone, and what it does not

At t ≈ 30 s after `bsd_init` (Home is not waited for), one kernel thread:
1. reads the CPM mailbox magic, sends four **LPB GET** queries (HSIO_N, HSIO_S, LSIO_E, LSIO_S), reads 13 pads;
2. puts the phy_fw clock, votes PCIe0's power subdomain on, releases PCIe0's three resets, polls PHY SRAM;
3. writes the PHY table, releases app_hold_phy, sets up the root port for gen 1 x1;
4. only if the CP pads read **off**: PERST low, stock's CP power-on (PM_WRST, CP_PWR, NRESET, CP_WRST, 10 ms steps), PERST high,
   LTSSM, config **reads** of the endpoint (ID, class, subsystem, link capability), then CP off in stock's order and every pad back.

It never loads firmware, never touches the CP's reserved memory, never writes the endpoint, never sends SPMI, never votes
anything off, and reads no IMEI/serial (the boot ROM has none to give). Android's next boot powers the CP from off itself
(`power_on_cp`), as after any reboot.

Risks, honestly: the PCIe0 power vote and resets are new frames on this phone (PCIe1's equivalents are physical, the HSIO_N
selector is from the vendor mapping table); the phy_fw clock is shared with USB (an "on" put only). If the CPM refuses a frame the
run stops there (`verdict: STOP … PCIe0 power vote` or `phy_fw clock put`) with nothing driven.

## Command (coordinator)

```
# after fresh binding review and admission (COORDINATION.md)
tools/hk queue add research/images/a7-ios-system-modem1 '' research/ios26-modem-r1/expect/modem1.yaml \
  --mach research/ios26-modem-r1/build/kernel.modem1.unstripped --note "modem rungs 1..4 (hk_dbg 0x41e1e1f)"
tools/hk queue admit <qid>
tools/hk queue run --once
```

(or directly `HK_LOCK=<coord> tools/hk cycle research/images/a7-ios-system-modem1 --expect research/ios26-modem-r1/expect/modem1.yaml
--mach research/ios26-modem-r1/build/kernel.modem1.unstripped`). Deadline is int3's 900 s; the modem lines come at about 30..32 s.

## Success lines (in order; `hk logs <attempt> --grep blazer-modem`)

```
blazer-modem: stage 4 (link), hold 0, force 0, starts in 30 s
blazer-modem: read: HSIO_N state 2
blazer-modem: read: HSIO_S state 2
blazer-modem: pad AP2CP_CP_PWR_ON (0x3c596000) param 0x… dmux 0x1 tx 0x… rx 0x…: not driven|driven low
blazer-modem: read: CP as found: off (power, resets low)
blazer-modem: ctrl: PCIe0 domain voted on. Next: resets init, power_up, perst
blazer-modem: ctrl: PHY SRAM ready after N polls, status 0x…
blazer-modem: phy: table in, PHY told. Next: reset app_hold_phy
blazer-modem: rc: set up
blazer-modem: cp: powered, ~32000 us. The CP boot ROM runs; PERST still low
blazer-modem: link: UP, attempt 1, N us after LTSSM on: gen 1, x1, …
blazer-modem: id: 144d:a5a5 class 0x028000 rev 0x.. subsys 0x…, endpoint lnkcap gen 4 x2: S5400 CP boot ROM, as Android reads it
blazer-modem: tidy: PERST low, LTSSM off, CP off (…), pads as found, errors 0x0
blazer-modem: verdict: PASS stage 4, at id: PCIe0 link gen 1 x1, endpoint 144d:a5a5, CP off again, frames 10
```

Then `python3 -I tools/probe_eval.py --row Cellular attempts/<id>` must say ⏳ active with that evidence, and the return check PASS.

## Reading a failure (one boot still answers which rung)

| Last line | Meaning | Next variable |
| --- | --- | --- |
| `read: CP as found: NOT off` + `STOP … CP not off as found` | ABL left a CP line high; nothing was driven | read the `pad …` lines; decide the safe off sequence (owner) |
| `STOP … phy_fw clock put` / `PCIe0 power vote` / `reset vote` | CPM refused the frame (reply word in detail) | frame encoding (lga_cpm_mappings / rst-cpm) |
| `STOP … PHY SRAM never ready` | clock or resets not effective | phy_fw clock rate/put, reset ids |
| `STOP … controller already live` | ABL left PCIe0 running | rerun with `blazer_modem_force=1` only after review |
| `link: attempt 4 failed … LTSSM 0x…` + `STOP … link never came up` | CP ROM did not train | CP2AP lines after power, PARTIAL_RST_N (LSIO_E state), CLKREQ |
| `STOP … not Samsung` / `no ID` | something else answered / config path | ATU/config window |
| no `blazer-modem` line after `stage 4 …` | the thread hung (mailbox poll is bounded: 1001 × 200 µs) | ramdump stacks |
