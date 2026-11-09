"""Point a Wibble Wobble APK or IPA at your own Puniemu server.

Usage:
    python3 patch_client.py <input.apk|input.ipa> <address> [output] [--keep-https]

<address> is a host, optionally with a port: 100.64.0.10, homelab, homelab:8081.

Rewrites the server address in place (same byte length, padded with '/'), so no
file structure changes. The address must fit the smallest slot in the file:
16 characters for wibblewobble.de builds, 14 for the WibWob Reload APK.

By default the client is also switched to plain HTTP, the same change WibWob
Reload makes: the game's standalone "https://" scheme string becomes "http://",
and on iOS an App Transport Security exception is added so iOS allows it.
Pass --keep-https if your server sits behind HTTPS with a real certificate.

Afterwards:
    APK: sign it (e.g. java -jar uber-apk-signer.jar -a <output> --allowResign)
    IPA: sideload with Sideloadly or AltStore (they sign it for you)
"""
import plistlib
import re
import sys
import zipfile

# Addresses known to be baked into clients. Add more if a build uses another.
KNOWN_HOSTS = [
    rb"31\.70\.145\.158(?::\d+)?",               # wibblewobble.de builds (ports 80/81/85 seen)
    rb"s-ywp-us-gameserver\.hangame\.co\.jp",    # original NHN build
    rb"wibwob\.ddns\.net",                       # "Reloaded" build
    rb"127\.0\.0\.1:876[56]",                     # WibWob Reload (WibWobPadaBoom) universal APK
]
HOST = re.compile(b"|".join(KNOWN_HOSTS))
# Optional scheme in front, then the host, then '/' padding
SLOT = re.compile(rb"(https?://)?(?:" + HOST.pattern + rb")/*")
# The scheme the game prepends to the bare game-server host (exactly one per binary)
SCHEME = b"\x00https://\x00"


def patch_slots(data, domain, name, plain_http):
    count = 0

    def repl(m):
        nonlocal count
        scheme, old = m.group(1) or b"", m.group()[len(m.group(1) or b""):]
        host = re.match(rb"[^/]+", old).group()
        if plain_http and scheme == b"https://":
            scheme, old = b"http://", b"/" + old          # one byte freed by the shorter scheme
        room = len(old) - (1 if old.endswith(b"/") else 0)   # keep the path separator
        if len(domain) > room:
            raise SystemExit(
                f"'{domain.decode()}' is {len(domain)} characters but {name} only has room for {room} "
                f"(slot for {host.decode()}). Use a shorter address: see homelab/README.md.")
        count += 1
        return scheme + domain + b"/" * (len(old) - len(domain))

    data = SLOT.sub(repl, data)
    if plain_http and count and SCHEME in data:
        if data.count(SCHEME) == 1:
            data = data.replace(SCHEME, b"\x00http://\x00\x00")
            print(f"  {name}: game server scheme set to http://")
        else:
            print(f"  {name}: WARNING {data.count(SCHEME)} standalone https:// strings, scheme left unchanged")
    return data, count


def patch_json(data, domain, plain_http):
    """Plain-text JSON can change length, so swap the host cleanly."""
    pattern = re.compile(rb"https?://(?:" + HOST.pattern + rb")")
    scheme = b"http://" if plain_http else None
    return pattern.subn(lambda m: (scheme or m.group().split(b"//")[0] + b"//") + domain, data)


def patch_info_plist(data):
    """Allow plain HTTP on iOS (App Transport Security exception)."""
    binary = data.startswith(b"bplist")
    plist = plistlib.loads(data)
    plist.setdefault("NSAppTransportSecurity", {})["NSAllowsArbitraryLoads"] = True
    return plistlib.dumps(plist, fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML)


def fix_ipa_permissions(info, data):
    """IPAs zipped on Windows carry no Unix permissions (mode 000), which iOS
    sideloaders reject as "no permission". Give every entry normal modes and
    make Mach-O binaries executable."""
    info.create_system = 3  # Unix
    if info.is_dir():
        mode = 0o40755
    elif data[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
        mode = 0o100755
    else:
        mode = 0o100644
    info.external_attr = (mode << 16) | (0x10 if info.is_dir() else 0)


def is_target(name):
    return (
        name.endswith("libSGF.so")
        or name.endswith("hsp_launching_zone.xml")
        or re.fullmatch(r"Payload/[^/]+\.app/[^/.]+", name) is not None   # iOS main executable
    )


def is_signature(name, apk):
    if apk:
        return name.startswith("META-INF/") and name.rsplit(".", 1)[-1] in ("SF", "RSA", "DSA", "EC", "MF")
    return False


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    plain_http = "--keep-https" not in sys.argv
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)
    src, domain = args[0], args[1].strip().lower()
    domain = re.sub(r"^https?://", "", domain).rstrip("/")
    dom = domain.encode()
    apk = src.lower().endswith(".apk")
    out = args[2] if len(args) > 2 else re.sub(r"(\.\w+)$", r"-patched\1", src)

    total = 0
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            if is_signature(info.filename, apk):
                continue
            data = zin.read(info)
            n = 0
            if info.filename.endswith("getLaunchingInfos.json"):
                data, n = patch_json(data, dom, plain_http)
            elif info.filename.endswith("wwr_server.conf"):
                # WibWob Reload's in-app relay target: "host|port"
                host, _, port = domain.partition(":")
                data, n = f"{host}|{port or 80}\r\n".encode(), 1
            elif is_target(info.filename):
                data, n = patch_slots(data, dom, info.filename, plain_http)
            elif plain_http and re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", info.filename):
                data = patch_info_plist(data)
                print(f"  {info.filename}: plain HTTP allowed (App Transport Security)")
            if n:
                print(f"  {info.filename}: {n} address(es) patched")
            total += n
            if not apk:
                fix_ipa_permissions(info, data)
            zout.writestr(info, data, compress_type=info.compress_type)

    if total == 0:
        sys.exit("No known server address found; nothing patched. Run inspect_client.py and add the host to KNOWN_HOSTS.")
    print(f"Wrote {out} ({total} addresses -> {domain}{'' if plain_http else ', HTTPS kept'})")


if __name__ == "__main__":
    main()
