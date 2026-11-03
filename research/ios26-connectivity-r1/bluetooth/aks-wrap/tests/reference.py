#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Independent reference for the v1 wrapped-key format (blazer_aks_wrap.inc), from its comment only."""
import hashlib
import hmac
import sys


def wrap(secret, handle, key_class, key):
    mac_key = hmac.new(secret, b'hackios aks wrap v1 mac', hashlib.sha256).digest()
    enc_key = hmac.new(secret, b'hackios aks wrap v1 enc', hashlib.sha256).digest()
    hdr = bytes([ord('h'), ord('k'), 1, len(key)])
    msg = b'HKW1' + hdr + handle.to_bytes(8, 'little') + key_class.to_bytes(4, 'little') + key
    tag = hmac.new(mac_key, msg, hashlib.sha256).digest()[:16]
    ks = b''.join(hmac.new(enc_key, tag + bytes([i]), hashlib.sha256).digest() for i in range(2))
    return hdr + tag + bytes(a ^ b for a, b in zip(key, ks))


def main():
    secret = bytes(range(32))
    key = bytes(0xa0 + i for i in range(32))
    want = wrap(secret, 0, 3, key).hex()
    got = [line.split()[-1] for line in sys.stdin if line.startswith('KAT class3 key32 ')]
    ok = got == [want]
    print('reference', want)
    print('KAT', 'PASS' if ok else 'FAIL', got)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
