# XNU for blazer

Target: XNU 12377 for iOS 26. No 12377 tree or port exists here yet; the route is being worked out in `research/ios26-route-r1`.

`ios16-base/patches/` is the iOS 16 port, the parts source. The rest of this file describes that build.

## iOS 16 build

`xnu-8796.121.2` (iOS 16.5, Darwin 22.5.0), built locally with
`research/laguna-foundation/kernel-blazer/xnu-build.sh`, `-j8 -k`.

The tree is `research/laguna-foundation/kernel-blazer/xnu-src/xnu-8796.121.2`: Apple's
base commit `c54f35c` plus uncommitted changes. `ios16-base/patches/` is a snapshot of those changes.

- `0001-osfmk-arm64-platform.patch`: display, panic dump, GIC, PSCI, startup.
- `0002-bsd-drivers-and-filesystems.patch`: `bsd/dev` drivers, HFS, APFS, ramfs, kern.
- `0003-iokit-drivers.patch`: `Mini*` services, GPU, battery, WLAN, platform expert.
- `0004-build-libkern-pexpert-other.patch`: configuration, makefiles, libkern, pexpert.

Apply in order to a clean `c54f35c`:

    for p in ios16-base/patches/*.patch; do git apply --whitespace=nowarn "$p"; done

The result has tree hash `81a628e74daa9eade11c2e58fbd07983175d0998`. `BUILD/` and four
`.orig`/`.rej` leftovers are not in the patches. The patches go stale when the tree changes.

- Older form of the changes: `research/workspace/hackios-xnu-kernel/xnu/redwood.patch`;
  new files: `research/workspace/hackios-xnu-kernel/xnu/files/`. `apply.sh` and `export.sh`
  go each way.
- After a patch, remove that build's `BUILD/obj`: generated configuration has absolute paths.
- RC=2 in the export-list tail can follow a successful link. Check the output.
- Pending UFS patches, unapplied:
  `research/laguna-usb-fix/native-fleet-20261031/N914-integration-next-candidate/patches/`.

Current hardware state is in `../BLAZER.md`.
