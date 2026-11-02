# Security

## This software isn't secure, by design

This is an experimental bring-up. Apple's security model is largely switched off:

- The kernel uses permissive policies in place of AMFI and Sandbox, so code signing isn't enforced as on stock iOS.
- There's no Secure Enclave, so a passcode encrypts nothing.
- Boot-image signing uses a test key on an unlocked bootloader.

**Don't put real data or accounts on a phone running it, and don't connect one to a network you need to trust.** These properties aren't vulnerabilities to report.

## What to report

- An identifier, dump, key, firmware or Apple file committed to this repository, now or in its history
- A tool that can write, flash, erase or change a slot on a phone in a way its documentation doesn't say
- A hole in `tools/bootios` or the image tool's hash pins that would let a wrong image or input through
- A secret or a token exposed by CI

## How to report

Don't quote the sensitive value in an issue. The repository is private: tell the owner, `TheAndersMadsen`, directly on GitHub, or open an issue that names only the file and commit. Say what you saw, and if it's on a phone, the attempt's name.

There are no released versions and no support period. Fixes go to `ios26`. Removing something from history needs the owner's confirmation, because it rewrites the branch.
