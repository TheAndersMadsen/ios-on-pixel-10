# H3 verdict (QEMU, 2026-11-03, m1box rig): REJECTED as stated; lane 4 stops under GOAL.md section 7

H3 (intent-r12.json): container registration lacks the user persona because the stock first-boot creator
`usermanagerd --init` never runs; running it creates the session and the system-session personas, the type-6 lookups
stop failing, and registration proceeds.

| Discriminator (intent-r12) | Result | Run |
| --- | --- | --- |
| the creator executes, its own console line | YES: `****** IN UMD_INIT ****` / `STARTING EARLYBOOT SETUP` / `DONE UMD_INIT` (boot task, launchd "Doing boot task") | r13, r14, r15b (rd=ufsroot0) |
| `Unable to find persona with type 6` stops | YES: 0 (rd=md0 runs: 141-323) | r13, r14, r15b |
| daemon finds a session, no "could not find the requested session" | NO: still present; daemon knows a fresh user each boot but `no personas found for user ...` | r14, r15b |
| `Created mobile user` / `Allocated kernel persona ... Type` | not visible (boot-task os_log is not mirrored); no persona exists for the user per the daemon | r14, r15b |
| lsd registers a container app | NO: lsd aborts at launch: `container lookup query: 3b(76) INVALID_PERSONA` -> `Could not get user container URL! Must abort.` (17-20 aborts per run); the registrar's enumeration never returns | r14, r15b |

Failed hypotheses (two, materially different):
1. H3 (boot mode): running the stock creator is not sufficient. The boot mode was the reason it never ran (rd=md0 =
   libignition spec "ramdisk", PerformAlways/PerformInRestore boot tasks only), and fixing that removes the type-6 errors,
   but per-user personas still do not exist and lsd now aborts instead of refusing.
2. H3b (persistence): the seeded empty persona.kb (atomic replace on varfs without RENAME_SWAP) is not the cause: removing
   it (r15b) changes nothing.

Next blocker (static inference, not tested): usermanagerd creates the per-user default personas (Personal/System/Default/
Universal) only in its session loader after `MKBUserSessionLoadKeybagForUser` succeeds (usermanagerd.otool 71227-71591,
"Failed to load keybag for session" returns before the personas). No usermanagerd AppleKeyStore call appears in the SWEET
AKS console lines (r15b), so the user-session keybag path is not served in QEMU. Supported AKS user-session behaviour is
the next step; it is SEP-adjacent (GOAL.md section 7 out-of-scope list: no SEP or identity emulation), so it needs an
owner decision before any work.

Receipts: STATIC.md, PRIOR-ART.md, result-r13.json, ../h3-r14/intent-r14.json, ../h3-r15/{intent-r15.json,
run-r15-void.json,result-r15b.json}; consoles under /data/hackios-qemu/research/ios26-apps-r1/runs/.
