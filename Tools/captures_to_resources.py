"""Turn saved server responses into Resources/ files for Puniemu.

Give it a folder of response bodies, one file per response, in either form:
  - the body exactly as the server sent it (still encrypted), or
  - the decrypted JSON.
It works out which per file. Decrypting needs `pip install cryptography`;
already-decrypted JSON needs nothing.

From each response it takes the master tables (ywp_mst_*) and the handful of
settings Puniemu reads from Resources/, and writes <name>.txt in the shape the
server loads. Player data (ywp_user_*) is never written.

By default it only fills gaps: files that are missing, and files listed in
Resources.from-wibwob.list (the Wibble Wobble stand-ins), which it replaces.
Tables you fetched yourself are left alone unless --overwrite is given.

    python3 Tools/captures_to_resources.py captures/ --resources Resources --dry-run
    python3 Tools/captures_to_resources.py captures/ --resources Resources

Rebuild the server image afterwards: Resources are compiled in.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# Non-table values the server keeps in Resources/
SETTINGS = {"mstVersionMaster", "shopSaleList", "hitodamaShopSaleList", "ymoneyShopSaleList", "noticePageList",
            "noticePageListFlg", "teamEventButtonHiddenFlg", "responseCodeTeamEvent", "mstMapMobPeriodNoList",
            "gachaStampList"}


def read_response(path):
    """Returns (document, how) for one saved response, or (None, reason)."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None, "not text"
    if not text:
        return None, "empty"
    if text[0] in "{[":
        try:
            return json.loads(text), "json"
        except ValueError:
            return None, "broken JSON"
    try:
        sys.path.insert(0, HERE)
        from fetch_puni_resources import decrypt_response
    except ImportError:
        return None, "encrypted, and the cryptography package is not installed"
    try:
        return decrypt_response(text), "decrypted"
    except Exception as e:  # wrong key, truncated body, not a game response
        return None, f"could not decrypt ({type(e).__name__})"


def wanted(key, value):
    if value in (None, "", [], {}):
        return False
    if key.startswith("ywp_user"):
        return False
    return key.startswith("ywp_mst_") or key in SETTINGS


def as_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captures", help="folder of saved response bodies")
    ap.add_argument("--resources", default="Resources")
    ap.add_argument("--overwrite", action="store_true", help="also replace tables that are not stand-ins")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()

    root = os.path.dirname(os.path.abspath(args.resources))
    list_path = os.path.join(root, "Resources.from-wibwob.list")
    standins = set()
    if os.path.exists(list_path):
        with open(list_path, encoding="utf-8") as f:
            standins = {line.strip()[:-4] for line in f if line.strip().endswith(".txt")}

    found = {}       # name -> (text, source file)
    seen_twice = []
    files = sorted(os.listdir(args.captures))
    for name in files:
        path = os.path.join(args.captures, name)
        if not os.path.isfile(path):
            continue
        doc, how = read_response(path)
        if not isinstance(doc, dict):
            print(f"  skipped {name}: {how if doc is None else 'not a response object'}")
            continue
        keys = [k for k, v in doc.items() if wanted(k, v)]
        print(f"  {name}: {how}, {len(keys)} usable of {len(doc)} keys")
        for key in keys:
            text = as_text(doc[key])
            if key in found and found[key][0] != text:
                seen_twice.append((key, found[key][1], name))
            found[key] = (text, name)

    new, replaced, kept, same = [], [], [], []
    for key in sorted(found):
        text = found[key][0]
        dest = os.path.join(args.resources, key + ".txt")
        if not os.path.exists(dest):
            new.append(key)
        else:
            with open(dest, encoding="utf-8") as f:
                current = f.read()
            if current == text:
                same.append(key)
                continue
            if key in standins or args.overwrite:
                replaced.append(key)
            else:
                kept.append(key)
                continue
        if not args.dry_run:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(text)

    print(f"\nresponses read: {len(files)}; tables and settings found: {len(found)}")
    print(f"new files: {len(new)} {new[:12]}")
    print(f"replaced ({'stand-ins and others' if args.overwrite else 'Wibble Wobble stand-ins'}): {len(replaced)} {replaced[:12]}")
    print(f"already identical: {len(same)}")
    if kept:
        print(f"left alone (differs from your fetched copy; use --overwrite to take the captured one): {len(kept)} {kept[:12]}")
    for key, first, second in seen_twice[:10]:
        print(f"  note: {key} differs between {first} and {second}; used {second}")
    # What the server needs that no capture has supplied yet
    needs_path = os.path.join(HERE, "puniemu_required_resources.txt")
    if os.path.exists(needs_path):
        with open(needs_path, encoding="utf-8") as f:
            needs = [line.strip() for line in f if line.strip()]
        open_items = [n for n in needs if (n.startswith("ywp_mst_") or n in SETTINGS) and n not in found
                      and (n in standins or not os.path.exists(os.path.join(args.resources, n + ".txt")))]
        print(f"still not captured ({len(open_items)}): {' '.join(open_items)}")
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    done = set(replaced)
    if done and os.path.exists(list_path):
        with open(list_path, encoding="utf-8") as f:
            lines = [line for line in f if line.strip()[:-4] not in done]
        with open(list_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print(f"stand-ins still in use: {len(lines)} (see Resources.from-wibwob.list)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
