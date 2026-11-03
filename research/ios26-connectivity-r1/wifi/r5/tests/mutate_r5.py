#!/usr/bin/env python3
"""HOST ONLY. W1 r5 mutants: each edit of the real r5 sources must make ring_oracle, console_oracle or join2_oracle_r5 fail. Builds into build/mut."""
import os, subprocess, sys, shutil
H = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(H, "..", "src")
X = os.environ.get("XNU", "/data/hackios-qemu/wifi-r4/xnu") + "/bsd/dev"
L = os.environ.get("LLVM", os.path.expanduser("~/.local/share/hackios-host/llvm/bin"))
FL = ["-std=c11", "-O1", "-DBLAZER", "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-Wno-format", "-w"]
M = [
    ("blazer_bcm4390_ring.c", "#define RX_BUFS         1024u", "#define RX_BUFS         64u", "r4's 64 buffers"),
    ("blazer_bcm4390_ring.c", "#define RX_POST_DEPTH   (RX_BUFS + 64u)", "#define RX_POST_DEPTH   (RX_BUFS + 1u)", "post ring with no room over"),
    ("blazer_bcm4390_ring.c", "#define RX_CPL_DEPTH    1024u", "#define RX_CPL_DEPTH    128u", "r4's completion depth"),
    ("blazer_bcm4390_ring.c", "#define B4_DMA_NEEDED   0x280000u", "#define B4_DMA_NEEDED   0x60000u", "r4's host memory"),
    ("blazer_bcm4390_ring.c", "p->max_rxbufs != 0 && p->max_rxbufs < RX_BUFS ? p->max_rxbufs : RX_BUFS", "RX_BUFS", "cap ignored"),
    ("blazer_bcm4390_ring.c", "p->max_rxbufs != 0 && p->max_rxbufs < RX_BUFS ? p->max_rxbufs : RX_BUFS", "p->max_rxbufs < RX_BUFS ? p->max_rxbufs : RX_BUFS", "0 taken as a cap"),
    ("blazer_bcm4390_ring.c", "#define RX_BUF_BYTES    2048u", "#define RX_BUF_BYTES    2032u", "buffer under 0x7f8"),
    ("blazer_bcm4390_ring.c", "p->rx_items, p->rx_bytes, p->rx_dropped, p->fw_rx_nobuf);", "p->rx_items, p->rx_bytes, p->rx_dropped, 0u);", "witness without the drop count"),
    ("blazer_bcm4390_ring.c", "return post_rx(p, i);\n}", "return 0;\n}", "completion not reposted"),
    ("blazer_bcm4390.c", 'static const char tag[] = "EL: 30 b8c8 ";', 'static const char tag[] = "EL: 30 b8c";', "tag too loose"),
    ("blazer_bcm4390.c", 'static const char tag[] = "EL: 30 b8c8 ";', 'static const char tag[] = "EL: 30 b8c9 ";', "wrong format number"),
    ("blazer_bcm4390.c", "if (p->fw_rx_nobuf++ == 0) {", "if (p->fw_rx_nobuf++ >= 0) {", "said every time"),
    ("blazer_bcm4390.c", "\t\t\t\tb4_console_note(p, line);\n", "", "whole lines not counted"),
    ("blazer_bcm4390_join.c", "bool m1 = status == 5u || status == SUP_KEYED || (status >= 8u && status <= 11u);", "bool m1 = status == SUP_KEYED;", "M1 only when keyed"),
    ("blazer_bcm4390_join.c", "bool m1 = status == 5u || status == SUP_KEYED || (status >= 8u && status <= 11u);", "bool m1 = status != SUP_WAIT_M1;", "M1 for every state but 4"),
    ("blazer_bcm4390_join.c", '"waiting for M3", "preparing M4"', '"preparing M4", "waiting for M3"', "state names out of order"),
]
def build(srcdir, out, which):
    if which == "ring":
        a = [f"{L}/clang", *FL, "-iquote", srcdir, "-iquote", X, f"{H}/ring_oracle.c", "-o", out]
    elif which == "console":
        a = [f"{L}/clang", *FL, "-iquote", srcdir, "-iquote", X, f"{H}/console_oracle.c", f"{srcdir}/blazer_bcm4390.c", "-o", out]
    else:
        a = [f"{L}/clang", *FL, "-iquote", srcdir, "-iquote", X, f"{H}/join2_oracle_r5.c", f"{srcdir}/blazer_bcm4390_scan.c", "-o", out]
    return subprocess.run(a, capture_output=True).returncode
env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0")
caught = 0
for i, (f, a, b, why) in enumerate(M):
    d = os.path.join(H, "build", "mut", str(i))
    shutil.rmtree(d, ignore_errors=True)
    shutil.copytree(SRC, d)
    s = open(os.path.join(d, f)).read()
    if s.count(a) < 1:
        sys.exit(f"mutant {i} ({why}): anchor not found")
    open(os.path.join(d, f), "w").write(s.replace(a, b, 1))
    dead = False
    for w in ("ring", "console", "join"):
        o = os.path.join(d, w)
        if build(d, o, w) != 0:
            dead = True; break
        if subprocess.run([o], capture_output=True, env=env).returncode != 0:
            dead = True; break
    caught += dead
    print(f"mutant {i:2}: {why}: {'caught' if dead else 'SURVIVED'}")
print(f"mutate_r5: {caught}/{len(M)} caught")
sys.exit(0 if caught == len(M) else 1)
