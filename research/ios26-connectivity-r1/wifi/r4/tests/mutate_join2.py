#!/usr/bin/env python3
"""HOST ONLY. W1 r4: each mutant of the r4 join (r3's mutants plus r4's, and its gate) must make join2_oracle fail. Builds in a temp dir; the sources are untouched.

  python3 -I mutate_join2.py      exit 0: every mutant caught
"""
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
X = os.environ.get("XNU", "/data/hackios-qemu/wifi-r4/xnu")
L = os.environ.get("LLVM", os.path.expanduser("~/.local/share/hackios-host/llvm/bin"))

J, S = "blazer_bcm4390_join.c", "blazer_bcm4390_scan.c"
MUTANTS = [
    ("Android's wpa_auth", J, "#define WPA_ANDROID     0x2048080u", "#define WPA_ANDROID     0x80u"),
    ("Android's wsec", J, "#define WSEC_ANDROID    0x0006u", "#define WSEC_ANDROID    0x0004u"),
    ("Android's algos", J, "#define ALGOS_ANDROID   0x14014u", "#define ALGOS_ANDROID   0x10u"),
    ("no roam step", J, 'if (note_step(p, "roam_off", 0) || clear_security(p)) {', "if (clear_security(p)) {"),
    ("action byte", J, "#define PI_ACTION_AT    13u", "#define PI_ACTION_AT    12u"),
    ("passphrase offset", J, "jn_put16(pi, PI_PASS_AT + 2, (uint16_t)(PI_FIXED + net->ssid_len));", "jn_put16(pi, PI_PASS_AT + 2, (uint16_t)PI_FIXED);"),
    ("no padding to 4", J, "uint32_t size = (PI_FIXED + net->ssid_len + net->pass_len + 3u) & ~3u;", "uint32_t size = PI_FIXED + net->ssid_len + net->pass_len;"),
    ("tuple order", J, "{ 0x000fac18u, 0x000fac08u,", "{ 0x000fac08u, 0x000fac18u,"),
    ("targeted dwell in method 1", J, "#define JOIN_BCAST_ACTIVE_MS 80u", "#define JOIN_BCAST_ACTIVE_MS 320u"),
    ("no wildcard", J, "memset(j + JP_ASSOC + JA_BSSID, 0xff, 6);", "memcpy(j + JP_ASSOC + JA_BSSID, p->jn_bssid, 6);"),
    ("method 2 keeps r2's mfp", J, "uint32_t mfp = p->jn_mfp == MFP_REQUIRED ? MFP_REQUIRED : 0;", "uint32_t mfp = p->jn_mfp;"),
    ("method 2 ignores pairwise TKIP", J, "(p->jn_group_tkip || p->jn_pair_tkip ? WSEC_TKIP : 0u)", "(p->jn_group_tkip ? WSEC_TKIP : 0u)"),
    ("no disassociation", J, "\t\t\tif (part(p)) {", "\t\t\tif (0 && part(p)) {"),
    ("no forget after method 1 keyed", J, "\trc = read_join_ver(p) || join_tries(p);\n\tnet_forget(p);", "\trc = read_join_ver(p) || join_tries(p);"),
    ("method 2's failure doesn't stop", J, "\tif (last) {\n\t\treturn p1_halt(p, code, detail);", "\tif (0) {\n\t\treturn p1_halt(p, code, detail);"),
    ("method 1's events count against 2", J, "\tp->jn_sup_failed = false;\n\tp->jn_was_up = false;", "\tp->jn_was_up = false;"),
    ("no sup_wpa before up", J, 'if (set_int(p, "sup_wpa", 1, &st)) {', 'if (set_int(p, "sup_wpa", 0, &st)) {'),
    ("keyed line names the wrong method", J, "p->jn_method == 1 ? \"Android's order", "p->jn_method == 2 ? \"Android's order"),
    ("channel order", J, "if (p->jn_nchans == 0 || rssi > p->jn_chan_rssi[0]) {", "if (p->jn_nchans == 0 || rssi < p->jn_chan_rssi[0]) {"),
    ("wsec_info buffers left", J, "\tjn_wipe(b, sizeof(b));\n\tb4_wipe_ioctl(p);\n\treturn rc;", "\tjn_wipe(b, sizeof(b));\n\treturn rc;"),
    ("no delete of method 1's entry", J, "if (pass_info(p, PI_DEL, &st)) {", "if (pass_info(p, PI_ADD, &st)) {"),
    ("method 1 refusal ignored", J, "\tif (st != 0) {\n\t\tp->ops.log(p->ops.ctx, \"join: method 1 refused at join_pref", "\tif (0) {\n\t\tp->ops.log(p->ops.ctx, \"join: method 1 refused at join_pref"),
    ("gate: disassociation in a dry run", S, "{ WLC_DISASSOC, NULL, B4_GATE_ARMED }", "{ WLC_DISASSOC, NULL, B4_GATE_DRY }"),
    ("gate: 5 probes", S, "#define JW_NPROBES      4u", "#define JW_NPROBES      5u"),
    ("gate: 3 channels", S, "#define JW_MAX_CHANS    2u", "#define JW_MAX_CHANS    3u"),
    # r4
    ("r4: no buf_key_b4_m4", J, 'if (set_int(p, "buf_key_b4_m4", 1, &st)) {', 'if (set_int(p, "buf_key_b4_m4", 0, &st)) {'),
    ("r4: PM 1", J, "\t\t\tjn_put32(pm, 0, 0);", "\t\t\tjn_put32(pm, 0, 1);"),
    ("r4: PM refusal stops", J, '"join: PM to 0 (off) for the handshake: status %d\\n", p->ioc_status);', '"join: PM to 0 (off) for the handshake: status %d\\n", p->ioc_status);\n\t\t\tif (p->ioc_status != 0) {\n\t\t\t\treturn p1_halt(p, P1_STOP_SECURITY, 1);\n\t\t\t}'),
    ("r4: no rx look after a failed method", J, "\tif (rx_look(p)) {\n\t\treturn (int)p->stop;\n\t}\n\tif (last) {", "\tif (last) {"),
    ("r4: no rx look after keying", J, "return say_band(p) || rx_look(p) ? (int)p->stop : 0;", "return say_band(p);"),
    ("r4: rx look before the band", J, "return say_band(p) || rx_look(p) ? (int)p->stop : 0;", "return rx_look(p) || say_band(p) ? (int)p->stop : 0;"),
    ("r4: counters: wrong word for rxnobuf", S, '{ 19, "rxnobuf" }', '{ 18, "rxnobuf" }'),
    ("r4: counters: no delta", S, "\t\t\tif (p->rxc_ok) {\n\t\t\t\tx = v[i] - p->rxc[i];", "\t\t\tif (0) {\n\t\t\t\tx = v[i] - p->rxc[i];"),
    ("r4: counters: last look not kept", S, "\tmemcpy(p->rxc, v, sizeof(p->rxc));\n\tp->rxc_ok = true;", "\tp->rxc_ok = true;"),
    ("r4: gate: PM before stage JOIN", S, "{ WLC_SET_PM, NULL, B4_GATE_DRY }", "{ WLC_SET_PM, NULL, B4_GATE_PASSIVE }"),
    ("r4: gate: no buf_key_b4_m4", S, '{ WLC_SET_VAR, "buf_key_b4_m4", B4_GATE_DRY }, ', ''),
    ("gate: any flags", S, "return sc_get16(j, JP_ASSOC + JA_FLAGS) == 0 && sc_get16(j, JP_ASSOC + JA_BSSID_CNT) == 0;\n}\n\n/* Only a join for one", "return sc_get16(j, JP_ASSOC + JA_BSSID_CNT) == 0;\n}\n\n/* Only a join for one"),
]


def build_run(d):
    exe = os.path.join(d, "o")
    cc = [os.path.join(L, "clang"), "-std=c11", "-O1", "-g", "-DBLAZER", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-w",
          "-iquote", os.path.join(d, "src"), "-iquote", os.path.join(X, "bsd/dev"), os.path.join(HERE, "join2_oracle.c"), os.path.join(d, "src", S), "-o", exe]
    # join2_oracle.c includes "blazer_bcm4390_join.c": the mutated copy comes first on the quote path only if the oracle sits beside it
    shutil.copy(os.path.join(HERE, "join2_oracle.c"), os.path.join(d, "src", "join2_oracle.c"))
    cc[cc.index(os.path.join(HERE, "join2_oracle.c"))] = os.path.join(d, "src", "join2_oracle.c")
    if subprocess.run(cc, capture_output=True).returncode:
        return "build failed"
    r = subprocess.run([exe], capture_output=True, text=True, timeout=300)
    return "pass" if r.returncode == 0 else "caught"


def main():
    with tempfile.TemporaryDirectory() as t:
        os.mkdir(os.path.join(t, "src"))
        for f in (J, S, "blazer_pcie1.h"):
            shutil.copy(os.path.join(SRC, f), os.path.join(t, "src", f))
        base = build_run(t)
        if base != "pass":
            print(f"unmutated: {base}")
            return 1
        caught = 0
        for name, f, old, new in MUTANTS:
            path = os.path.join(t, "src", f)
            orig = open(path).read()
            if orig.count(old) != 1:
                print(f"mutant {name}: its text is not in {f} exactly once")
                return 1
            open(path, "w").write(orig.replace(old, new))
            res = build_run(t)
            open(path, "w").write(orig)
            print(f"mutant {name}: {res}")
            caught += res == "caught"
        print(f"join2 mutants: {caught}/{len(MUTANTS)} caught")
        return 0 if caught == len(MUTANTS) else 1


sys.exit(main())
