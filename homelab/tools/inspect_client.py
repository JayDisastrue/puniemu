"""List server addresses in a Wibble Wobble APK/IPA and whether the IPA is decrypted.

Usage: python3 inspect_client.py <file.apk|file.ipa>
"""
import sys, zipfile, re, struct, plistlib

def cryptids(d, off=0):
    if struct.unpack_from('>I', d, off)[0] == 0xcafebabe:          # fat binary
        n = struct.unpack_from('>I', d, off + 4)[0]
        out = []
        for i in range(n):
            o = struct.unpack_from('>I', d, off + 8 + i * 20 + 8)[0]
            out += cryptids(d, o)
        return out
    magic = struct.unpack_from('<I', d, off)[0]
    if magic not in (0xfeedface, 0xfeedfacf):
        return ['not mach-o']
    ncmds = struct.unpack_from('<I', d, off + 16)[0]
    p = off + (32 if magic == 0xfeedfacf else 28)
    out = []
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', d, p)
        if cmd in (0x21, 0x2C):                                     # LC_ENCRYPTION_INFO(_64)
            out.append(struct.unpack_from('<I', d, p + 16)[0])
        p += size
    return out

URL = re.compile(rb'https?://[A-Za-z0-9.\-]+[A-Za-z0-9/._\-]*')

def hosts(name, data):
    found = sorted({m.group().decode() for m in URL.finditer(data)})
    keep = [u for u in found if not re.search(r'apple\.com|w3\.org|xml|schemas|adobe|google', u)]
    if keep:
        print(f'\n{name}'); [print('   ', u) for u in keep]

z = zipfile.ZipFile(sys.argv[1])
names = z.namelist()
if any(n.startswith('Payload/') for n in names):
    app = next(n.split('/')[1] for n in names if n.startswith('Payload/') and n.endswith('.app/Info.plist') and n.count('/') == 2)
    exe = plistlib.loads(z.read(f'Payload/{app}/Info.plist'))['CFBundleExecutable']
    binary = z.read(f'Payload/{app}/{exe}')
    ids = cryptids(binary)
    print('IPA executable:', exe, '| cryptid per arch:', ids, '->', 'DECRYPTED' if ids and all(i == 0 for i in ids) else 'ENCRYPTED or unknown')
    hosts(f'Payload/{app}/{exe}', binary)
for n in names:
    if n.endswith(('.so', '.xml', '.plist', '.json', '.dylib')) or '/Frameworks/' in n and '.' not in n.rsplit('/', 1)[-1]:
        hosts(n, z.read(n))
