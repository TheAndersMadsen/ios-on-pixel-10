#!/usr/bin/env python3
"""The network a Wi-Fi image joins: from the owner's secret file to an overlay only that image holds. Host only. Prints no name, no password, no key.

  mkwifisecret.py build [secret/wifi.secret]        secret/wifi.ovl and its SHA-256, for image_tool's --var-overlay. Prints the SHA-256 and sizes
  mkwifisecret.py check [secret/wifi.secret]        says what's wrong with the file, else yes/no facts about it (never a value)
  mkwifisecret.py mac                               a locally administered address to put in the file, new each time
  mkwifisecret.py wipe                              deletes what build made, and every image and scratch copy under secret/run and secret/imgview (tools/mkimage.py --secret). Keeps the secret file

The file, mode 600, under research/ios26-wifi-r1/secret/ (research/ is git-ignored, and this folder is 700):
  ssid=the network's name
  password=its password          8 to 63 characters, or 64 hex digits: a PSK. Leave the line out for an open network
  country=DK                     the two letters of where the phone is. Required: the firmware's own default is US
  rev=1                          optional: the CLM's revision for that country. Default: the firmware's choice
  mac=02:xx:xx:xx:xx:xx          optional. Without it the firmware's own random one for each boot

Blob versions (b4_net_parse). BWN1, 108 bytes: the 32-byte PMK made of the password and the name, as 802.11i says, and a random salt, so that a
hash of the image is no test of a guess. BWN2, 176 bytes (W1 r2, the default): BWN1 + the passphrase itself, because the BCM4390 firmware's own
supplicant runs on a passphrase: given only the PMK it never answered M1 (physical a7-wifi-join-r1; research/ios26-connectivity-r1/wifi/r2/FIX.md).
So a BWN2 image holds the password: keep it on the host, mode 600, and wipe it after the boot. A 64-hex PSK has no passphrase: BWN1 only.
A name or password with odd characters is fine: everything after the first = up to the line's end, nothing stripped but the newline.
A carriage return is refused (a file saved with CRLF line ends would put it in the name or the password).

Format: blazer_bcm4390_join.c b4_net_parse. Overlay: varfs_overlay.h. Group 26, as the audio covers' 24 and 25, never named in hk_overlay=: never applied, never a file in /private/var. Group 0 only holds a directory, for the image tool, which wants hk_overlay= with any overlay.
"""
import hashlib, os, secrets, shutil, struct, subprocess, sys
from pathlib import Path

R = Path(__file__).resolve().parents[1]
SECRET = R/'secret'
NB_BYTES = 108
NB_SSID_LEN = 24
NB_FLAGS = 25
NB_ABBREV = 26
NB_CCODE = 28
NB_REV = 32
NB_MAC = 36
NB_SSID = 44
NB_PMK = 76
NB2_PASS_LEN = 108
NB2_PASS = 109
NB2_BYTES = 176
F_OPEN, F_MAC = 1, 2
GROUP = 26
PATH = '/private/var/hkcover/wifi/net'
MKOVERLAY = R.parent/'ios26-overlay-r1/tools/mkoverlay.py'


def die(msg):
    sys.exit(f'mkwifisecret: {msg}')


def parse(path):
    if not path.exists(): die(f'no {path}')
    if path.stat().st_mode & 0o077: die(f'{path} is readable by others: chmod 600')
    fields = {}
    for n, line in enumerate(path.read_bytes().split(b'\n'), 1):
        if not line.strip() or line.startswith(b'#'): continue
        if b'=' not in line: die(f'line {n}: no =')           # Never the line itself: it could be the password
        k, v = line.split(b'=', 1)
        if b'\r' in v: die(f'line {n}: carriage return: save the file with LF line ends')
        k = k.decode('ascii', 'replace').strip()
        if k not in ('ssid', 'password', 'country', 'rev', 'mac'): die(f'line {n}: unknown key')
        if k in fields: die(f'{k} given twice')
        fields[k] = v
    for need in ('ssid', 'country'):
        if need not in fields: die(f'no {need}=')
    return fields


def pmk_of(password, ssid):
    if len(password) == 64 and all(c in b'0123456789abcdefABCDEF' for c in password):
        return bytes.fromhex(password.decode())
    if not 8 <= len(password) <= 63 or not all(32 <= c < 127 for c in password):
        die('password: 8 to 63 printable characters, or 64 hex digits')
    return hashlib.pbkdf2_hmac('sha1', password, ssid, 4096, 32)


def is_hex_psk(password):
    return len(password) == 64 and all(c in b'0123456789abcdefABCDEF' for c in password)


def blob(fields, version=2):
    if version not in (1, 2): die('blob version: 1 or 2')
    ssid = fields['ssid']
    if not 1 <= len(ssid) <= 32: die('ssid: 1 to 32 bytes')
    cc = fields['country'].decode('ascii', 'replace').strip().upper()
    if len(cc) != 2 or not all(c.isascii() and c.isalnum() for c in cc): die('country: two letters')
    if cc == '00': die('country: 00 is no country')
    rev = int(fields.get('rev', b'-1'))
    flags = 0
    mac = bytes(6)
    if 'mac' in fields:
        try: mac = bytes(int(x, 16) for x in fields['mac'].decode().strip().split(':'))
        except ValueError: die('mac: six hex bytes')
        if len(mac) != 6 or mac[0] & 1 or mac == bytes(6): die('mac: six hex bytes, not multicast, not zero')
        flags |= F_MAC
    if 'password' in fields:
        pmk = pmk_of(fields['password'], ssid)
    else:
        pmk = bytes(32)
        flags |= F_OPEN
    passphrase = b''
    if version == 2 and 'password' in fields:
        if is_hex_psk(fields['password']): die('password: a 64-hex PSK is no passphrase; BWN2 needs the passphrase itself')
        passphrase = fields['password']        # pmk_of above checked 8..63 printable ASCII
    b = bytearray(NB2_BYTES if version == 2 else NB_BYTES)
    b[0:4] = b'BWN2' if version == 2 else b'BWN1'
    struct.pack_into('<I', b, 4, version)
    b[8:24] = secrets.token_bytes(16)
    b[NB_SSID_LEN] = len(ssid)
    b[NB_FLAGS] = flags
    b[NB_ABBREV:NB_ABBREV + 2] = cc.encode()
    b[NB_CCODE:NB_CCODE + 2] = cc.encode()
    struct.pack_into('<i', b, NB_REV, rev)
    b[NB_MAC:NB_MAC + 6] = mac
    b[NB_SSID:NB_SSID + len(ssid)] = ssid
    b[NB_PMK:NB_PMK + 32] = pmk
    if version == 2:
        b[NB2_PASS_LEN] = len(passphrase)
        b[NB2_PASS:NB2_PASS + len(passphrase)] = passphrase
    return bytes(b)


def facts(fields):
    """Yes/no and lengths-free facts for `check`: nothing that narrows the name or the password down."""
    pw = fields.get('password', b'')
    return {'open network': 'password' not in fields, 'password is a 64-hex PSK': is_hex_psk(pw),
            'password starts or ends with a space': bool(pw) and (pw[:1] == b' ' or pw[-1:] == b' '),
            'name starts or ends with a space': fields['ssid'][:1] == b' ' or fields['ssid'][-1:] == b' ',
            'name is ASCII': all(32 <= c < 127 for c in fields['ssid']), 'BWN2 possible': 'password' not in fields or not is_hex_psk(pw)}


def build(path):
    fields = parse(path)
    data = blob(fields)
    SECRET.mkdir(mode=0o700, exist_ok=True)
    os.chmod(SECRET, 0o700)
    raw = SECRET/'wifi.net'
    fd = os.open(raw, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'wb') as f: f.write(data)
    spec = SECRET/'wifi.ovl.json'
    import json
    fd = os.open(spec, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'name': 'wifi-secret', 'groups': [
            {'name': 'hold', 'bit': 0, 'note': 'for the image tool: hk_overlay=1 applies only this', 'entries': [{'dir': '/private/var/hkwifi', 'mode': '700', 'uid': 0, 'gid': 0}]},
            {'name': 'wifi', 'bit': GROUP, 'note': 'never applied: blazer_wifi_net.c reads it', 'entries': [{'file': PATH, 'src': str(raw), 'sha256': hashlib.sha256(data).hexdigest(), 'mode': '600', 'uid': 0, 'gid': 0}]},
        ]}, f)
    out = SECRET/'wifi.ovl'
    p = subprocess.run([sys.executable, '-I', str(MKOVERLAY), 'build', str(spec), str(out)], capture_output=True, text=True)
    os.remove(raw)
    os.remove(spec)
    if p.returncode: die('mkoverlay failed: ' + p.stderr[-300:].replace(hashlib.sha256(data).hexdigest(), '...'))
    os.chmod(out, 0o600)
    print(f'{out}: {out.stat().st_size} bytes, SHA-256 {hashlib.sha256(out.read_bytes()).hexdigest()}. Group {GROUP} never named in hk_overlay=. Boot line needs hk_overlay=1')


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else SECRET/'wifi.secret'
    if cmd == 'build':
        build(path)
    elif cmd == 'check':
        f = parse(path)
        blob(f, 1)
        if facts(f)['BWN2 possible']: blob(f, 2)
        print('file reads fine')
        for k, v in facts(f).items(): print(f'  {k}: {"yes" if v else "no"}')
    elif cmd == 'mac':
        b = bytearray(secrets.token_bytes(6))
        b[0] = (b[0] & 0xfc) | 0x02
        print(':'.join(f'{x:02x}' for x in b))
    elif cmd == 'wipe':
        n = 0
        if (SECRET/'wifi.ovl').exists():
            (SECRET/'wifi.ovl').unlink()
            n += 1
        # rmtree removes the view's symlinks to bootchain's folder, never what they point at
        for d in (SECRET/'run', SECRET/'imgview'):
            if d.exists():
                n += sum(len(files) for _, _, files in os.walk(d))
                shutil.rmtree(d)
        print(f'{n} files gone. The secret file stays')
    else:
        die(__doc__)


if __name__ == '__main__':
    main()
