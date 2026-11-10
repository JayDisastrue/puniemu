"""Fetch the Japanese Puni Puni master tables into Resources/ for Puniemu.

The Japanese game server answers getMaster.nhn without a login. Each table is
saved as <out>/<table>.txt in the shape the server sent it, which is the shape
Puniemu embeds at build time.

    pip install cryptography
    python3 Tools/fetch_puni_resources.py --app-ver 4.177.0 --out Resources

It asks for one table at a time, with a pause in between, and can be re-run:
tables already saved are skipped unless --force is given.

This does not produce the files Puniemu's developers wrote by hand (stage_data,
gacha_pool, mission_cfg, rare_enemy, ...). The script lists what is still
missing when it finishes.
"""
import argparse
import base64
import gzip
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEY = bytes([0xa8, 0x65, 0xd7, 0xe5, 0xe2, 0x45, 0x8f, 0x8c, 0xe1, 0xb5, 0xec, 0xd0, 0x87, 0xe5, 0x45, 0x94])
SALT = b"0bk2kvtFE2"
GAMESERVER = "https://gameserver.yw-p.com/"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json", "Accept-Encoding": "identity",
           "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; Pixel 7 Build/TQ3A.230901.001)"}
HERE = os.path.dirname(os.path.abspath(__file__))
# Values the server sends next to the tables that Puniemu also reads from Resources/
SCALARS = ("mstVersionMaster", "shopSaleList", "hitodamaShopSaleList", "ymoneyShopSaleList")


def encrypt_request(payload):
    body = json.dumps(payload).encode()
    digest = hashlib.sha1(SALT + hashlib.sha1(SALT + b" " + body).digest()).digest()
    padder = padding.PKCS7(128).padder()
    enc = Cipher(algorithms.AES(KEY), modes.ECB()).encryptor()
    return base64.urlsafe_b64encode(enc.update(padder.update(digest + body) + padder.finalize()) + enc.finalize())


def decrypt_response(text):
    text = text.strip().replace("-", "+").replace("_", "/")
    text += "=" * (-len(text) % 4)
    dec = Cipher(algorithms.AES(KEY), modes.ECB()).decryptor()
    unpadder = padding.PKCS7(128).unpadder()
    raw = unpadder.update(dec.update(base64.b64decode(text)) + dec.finalize()) + unpadder.finalize()
    # 20 bytes of digest, then gzip
    return json.loads(gzip.decompress(raw[20:]).decode("utf-8"))


def get_master(app_ver, table):
    payload = {"appVer": app_ver, "deviceId": "d-" + "0" * 32, "level5UserId": "0", "osType": 2,
               "tableNames": table, "userId": "0", "ywpToken": "0"}
    req = urllib.request.Request(GAMESERVER + "getMaster.nhn", data=encrypt_request(payload),
                                 headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=180) as r:
        return decrypt_response(r.read().decode())


def save(out, name, value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(out, name + ".txt"), "w", encoding="utf-8") as f:
        f.write(text)


def read_list(path):
    with open(path, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app-ver", required=True, help="client version, e.g. 4.177.0")
    ap.add_argument("--out", default="Resources", help="output folder (default: Resources)")
    ap.add_argument("--tables", default=os.path.join(HERE, "puni_master_tables.txt"),
                    help="file with one table name per line")
    ap.add_argument("--only", nargs="*", help="fetch just these tables")
    ap.add_argument("--force", action="store_true", help="fetch tables that are already saved")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds to wait between requests")
    args = ap.parse_args()

    tables = args.only or read_list(args.tables)
    os.makedirs(args.out, exist_ok=True)
    saved, skipped, not_served, failed = [], [], [], []
    shown_shape = False
    for i, table in enumerate(tables, 1):
        tag = f"[{i}/{len(tables)}] {table}"
        if not args.force and os.path.exists(os.path.join(args.out, table + ".txt")):
            skipped.append(table)
            continue
        try:
            res = get_master(args.app_ver, table)
        except (urllib.error.URLError, ValueError, OSError) as e:
            print(f"{tag}: FAILED ({e})")
            failed.append(table)
            time.sleep(args.delay)
            continue
        if not shown_shape:
            # Printed once so a version refusal or an unexpected answer is easy to spot
            keys = {k: (v if isinstance(v, (int, float)) or (isinstance(v, str) and len(v) < 80) else type(v).__name__)
                    for k, v in res.items()}
            print(f"first answer looks like: {keys}")
            shown_shape = True
        value = res.get(table)
        if value in (None, "", [], {}):
            print(f"{tag}: not served")
            not_served.append(table)
        else:
            save(args.out, table, value)
            saved.append(table)
            print(f"{tag}: ok")
        for k in SCALARS:
            if res.get(k) is not None:
                save(args.out, k, res[k] if isinstance(res[k], (list, dict)) else str(res[k]))
        time.sleep(args.delay)

    print(f"\nsaved {len(saved)}, already had {len(skipped)}, not served {len(not_served)}, failed {len(failed)}")
    if failed:
        print("failed (run again to retry): " + " ".join(failed))
    needs_path = os.path.join(HERE, "puniemu_required_resources.txt")
    if os.path.exists(needs_path):
        needs = read_list(needs_path)
        missing = [n for n in needs if not os.path.exists(os.path.join(args.out, n + ".txt"))]
        print(f"Puniemu reads {len(needs)} resource files; {len(missing)} still missing from {args.out}:")
        for n in missing:
            print("  " + n)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
