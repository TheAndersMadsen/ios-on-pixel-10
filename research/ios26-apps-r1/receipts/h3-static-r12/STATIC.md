# H3 static pass: who creates the user session and persona (SOURCE/static, 2026-11-03)

Input: `research/ios26-root-r1/apple/dis/usermanagerd.otool` (iOS 26 usermanagerd text disassembly; ObjC selectors and
CFString keys unresolved). Helper analysis, every line below re-read by the owner thread against the file. Not QEMU.

## Findings (observation, `.otool` line)

- "getUserSessionKeybagData: could not find the requested session" (4131) and "USESSION_SET_UID was set but no
  UserSessionID was given!" (4258) come from one lookup that searches the in-memory session table.
- The table is filled only from disk: LoadAllUserSessions "Read user sessions in _gUserSessionTable" (67253) via
  diskLoadUserSessions reading `/private/var//keybags/usersession.kb` (81330).
- `main` branches on `--init` / `--switch` (strcmp 87660-87672). With no argument (the LaunchDaemon) it only loads
  sessions and the persona manifest; it contains no creation path.
- `--init` (umd_init; skips on diagnostics mode or an ephemeral data volume, 87881-87898) runs the early-boot task:
  "NO USER SESSIONS" (60949) -> "Mobile user not found" (61233) -> create primary session (bl 0x100052a24, 61365)
  -> "Created mobile user" (61397) -> system-session personas (bl 0x100095e18 at 61747; "Creating system session
  personas..." 152377) -> kpersona_alloc ("Allocated kernel persona with ID: %u, Type: %d" 122554).
- UM->kernel persona type map (0x10005b2e4, 92245-92322): UM 5 ("Default") -> kernel 6 = PERSONA_SYSTEM_PROXY. The
  launchd error "Unable to find persona with type 6" is about this system-session persona.
- Per-user personas wait on `MKBUserSessionLoadKeybagForUser` (71227, "Failed to load keybag for session" 71259);
  the system-session personas (61747) come before the AKS steps (61932+).

## QEMU observation that matches

`research/ios26-connectivity-r1/keychain-guest-r3/runs/bt-keychain-r1/console.log`: launchd logs "Skipping boot-task"
for every boot task, including fsck, mount-phase-1/2, data-protection, keybag and **usermanagerd**. No guest log on the
host contains "IN UMD_INIT".

## Consequence for H3

The chain "registration needs a persona, the persona needs a primary session" holds, but the missing piece is not
an AppleKeyStore bootstrap. It is that `usermanagerd --init`, the stock first-boot creator, never runs, because
launchd skips all boot tasks in these QEMU boots. Why launchd skips them is the next question. One-variable test:
let the stock `usermanagerd --init` run once before the daemon, with nothing fabricated. Discriminators: "IN UMD_INIT",
"Created mobile user", "Allocated kernel persona ... Type: 6", launchd's type-6 ESRCH gone, then whether lsd registers.
