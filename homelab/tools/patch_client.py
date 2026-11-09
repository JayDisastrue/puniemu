"""Point a Wibble Wobble APK or IPA at your own Puniemu server.

Usage:
    python3 patch_client.py <input.apk|input.ipa> <your-domain> [output]

Rewrites the game-server address in place (same byte length, padded with '/'),
so no file structure changes. The address must fit the smallest slot in the
file: 16 characters for wibblewobble.de builds, 14 for the WibWob Reload APK.
With the server on port 80 no port is needed, so a short Tailscale IP
(e.g. 100.64.0.10) or a MagicDNS machine name (e.g. homelab) fits.

Afterwards:
    APK: java -jar uber-apk-signer.jar -a <output> --allowResign
    IPA: sideload with Sideloadly or AltStore (they sign it for you)
"""
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
SLOT = re.compile(rb"(?:" + HOST.pattern + rb")/*")


def patch_slots(data, domain, name=""):
    """Replace each `<old host>////` run with `<domain>////` of identical length."""
    count = 0

    def repl(m):
        nonlocal count
        old = m.group()
        host = re.match(rb"[^/]+", old).group()
        room = len(old) - (1 if old.endswith(b"/") else 0)   # keep the path separator
        if len(domain) > room:
            raise SystemExit(
                f"'{domain.decode()}' is {len(domain)} characters but {name} only has room for {room} "
                f"(slot for {host.decode()}). Use a shorter address: see homelab/README.md.")
        count += 1
        # Extra '/' end up as leading slashes in the request path, which Puniemu strips.
        return domain + b"/" * (len(old) - len(domain))

    return SLOT.sub(repl, data), count


def patch_json(data, domain):
    """Plain-text JSON can change length, so swap the host cleanly."""
    return HOST.subn(domain, data)


def is_target(name):
    return (
        name.endswith("libSGF.so")
        or name.endswith("hsp_launching_zone.xml")
        or name.endswith("getLaunchingInfos.json")
        or re.fullmatch(r"Payload/[^/]+\.app/[^/.]+", name) is not None   # iOS main executable
    )


def is_signature(name, apk):
    if apk:
        return name.startswith("META-INF/") and name.rsplit(".", 1)[-1] in ("SF", "RSA", "DSA", "EC", "MF")
    return False


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src, domain = sys.argv[1], sys.argv[2].strip().lower()
    domain = re.sub(r"^https?://", "", domain).rstrip("/")
    dom = domain.encode()
    apk = src.lower().endswith(".apk")
    out = sys.argv[3] if len(sys.argv) > 3 else re.sub(r"(\.\w+)$", r"-patched\1", src)

    total = 0
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w") as zout:
        for info in zin.infolist():
            if is_signature(info.filename, apk):
                continue
            data = zin.read(info)
            if is_target(info.filename):
                if info.filename.endswith(".json"):
                    data, n = patch_json(data, dom)
                else:
                    data, n = patch_slots(data, dom, info.filename)
                if n:
                    print(f"  {info.filename}: {n} address(es) patched")
                total += n
            zout.writestr(info, data, compress_type=info.compress_type)

    if total == 0:
        sys.exit("No known server address found; nothing patched. Run inspect_client.py and add the host to KNOWN_HOSTS.")
    print(f"Wrote {out} ({total} addresses -> {domain})")


if __name__ == "__main__":
    main()
