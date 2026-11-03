#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Source-order check for S1 (COREMEM-INIT.md section 3.1): in gta_shared_init the coremem store follows the sysinit zero and precedes the
publication barrier; in gta_rung4 the readback follows gta_shared_init and precedes power-on and SMC START; the flag is set before the thread
starts. Usage: order_check.py src/blazer_gpu_tipc.c"""
import re, sys
s = open(sys.argv[1]).read()
def body(name):
    m = re.search(r'\n' + name + r'\(([^)]*)\)\n\{(.*?)\n\}\n', s, re.S)
    assert m, name
    return m.group(2)
def order(text, *keys):
    pos = [text.find(k) for k in keys]
    assert all(p >= 0 for p in pos), [k for k, p in zip(keys, pos) if p < 0]
    assert pos == sorted(pos), list(zip(keys, pos))
init = body('gta_shared_init')
order(init, 'gs_zero(si, GF_SZ_RGXFWIF_SYSINIT)', 'GF_SI_ui32MarkerVal, 1)', 'gs_w64(si + GTA_S1_SI_COREMEM, GTA_S1_COREMEM_VA)', 'GTA_SH_CONN + GF_CC_OS, GTA_OS_READY', 'aoc_barrier()')
assert init.count('GTA_S1_SI_COREMEM') == 1
r4 = body('gta_rung4')
order(r4, 'gta_send_firmware(&fw)', 'gta_shared_init(rung >= 6)', 'gta_s1_coremem_check(rung)', 'gta_power_on(&rgx)', 'aoc_smc(r)', 'gta_m2(rgx, rung >= 7)')
st = body('blazer_gpu_tipc_start')
order(st, 'on > 8', 'gta_s1_coremem = on == 7', 'kernel_thread_start(gta_thread')
m2 = body('gta_m2')
order(m2, 'gta_m2_state("boot")', 'gta_s1_gate("boot")', 'GF_CMD_HEALTH', 'GTA_CMD_STATEFLAGS', 'gta_s1_gate("final")', 'gta_m2_fwlog();\n\tgta_survey();\n\tif (e == GTA_K_EXECUTED)', 'M3 S1 PASS')
# No client stream in S1
for bad in ('KCCB_CMD_KICK', '0x2abc0065', 'HMFV3_', 'CCCB', 'UFO', 'CCB_CMD_', 'COMMONCONTEXT', 'FWMEMCONTEXT'):
    assert bad not in s, bad
# Only M2's two commands are ever written to the KCCB
assert len(re.findall(r'gta_kccb\(rgx, ', s)) == 2 and 'gta_kccb(rgx, 0, (uint32_t)GF_CMD_HEALTH' in s and 'gta_kccb(rgx, 1, GTA_CMD_STATEFLAGS' in s
print('order_check: OK (store after zero, before barrier; readback before power-on/SMC; flag before thread; gates around health; no KICK/CCB/UFO code)')
