"""Turn saved server responses into Resources/ files for Puniemu.

Give it either
  - a mitmproxy save file (what "File > Save" in mitmweb or `mitmdump -w` writes), or
  - a folder of response bodies, one file per response.
Bodies can be exactly as the server sent them (still encrypted) or already
decrypted JSON; it works out which. Decrypting needs `pip install cryptography`;
already-decrypted JSON needs nothing.

From each response it takes the master tables (ywp_mst_*) and the handful of
settings Puniemu reads from Resources/, and writes <name>.txt in the shape the
server loads. Player data (ywp_user_*) is never written.

By default it only fills gaps: files that are missing, and files listed in
Resources.from-wibwob.list (the Wibble Wobble stand-ins), which it replaces.
Tables you fetched yourself are left alone unless --overwrite is given.

    python3 Tools/captures_to_resources.py flows.mitm --resources Resources --dry-run
    python3 Tools/captures_to_resources.py flows.mitm --resources Resources

Rebuild the server image afterwards: Resources are compiled in.
"""
import argparse
import gzip
import json
import os
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
# Non-table values the server keeps in Resources/
SETTINGS = {"mstVersionMaster", "shopSaleList", "hitodamaShopSaleList", "ymoneyShopSaleList", "noticePageList",
            "noticePageListFlg", "teamEventButtonHiddenFlg", "responseCodeTeamEvent", "mstMapMobPeriodNoList",
            "gachaStampList"}


def tnet_items(data):
    """Yields the top-level values of a mitmproxy save file (a run of tnetstrings)."""
    pos = 0
    while pos < len(data):
        value, pos = tnet_value(data, pos)
        yield value


def tnet_value(data, pos):
    colon = data.index(b":", pos)
    size = int(data[pos:colon])
    start, end = colon + 1, colon + 1 + size
    body, kind = data[start:end], data[end:end + 1]
    if kind == b",":
        return body, end + 1
    if kind == b";":
        return body.decode("utf-8", "replace"), end + 1
    if kind == b"#":
        return int(body), end + 1
    if kind == b"^":
        return float(body), end + 1
    if kind == b"!":
        return body == b"true", end + 1
    if kind == b"~":
        return None, end + 1
    if kind in (b"]", b"}"):
        items, at = [], 0
        while at < len(body):
            item, at = tnet_value(body, at)
            items.append(item)
        if kind == b"]":
            return items, end + 1
        return dict(zip(items[0::2], items[1::2])), end + 1
    raise ValueError("not a mitmproxy save file")


def text_of(value):
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else (value or "")


def flow_responses(path):
    """Yields (label, body bytes) for every game request in a mitmproxy save file."""
    with open(path, "rb") as f:
        data = f.read()
    counts = {}
    for flow in tnet_items(data):
        if not isinstance(flow, dict):
            continue
        request, response = flow.get("request") or {}, flow.get("response") or {}
        name = text_of(request.get("path")).split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        body = response.get("content")
        if not name.endswith(".nhn") or not body:
            continue
        for header in response.get("headers") or []:
            if len(header) == 2 and text_of(header[0]).lower() == "content-encoding":
                encoding = text_of(header[1]).lower()
                try:
                    if "gzip" in encoding:
                        body = gzip.decompress(body)
                    elif "deflate" in encoding:
                        body = zlib.decompress(body)
                except (OSError, zlib.error):
                    pass
        counts[name] = counts.get(name, 0) + 1
        yield f"{name[:-4]} #{counts[name]}", body, request.get("content")


# Files the server passes to the game untouched, so they must be stored exactly as received
SENT_AS_IS = {"ywp_mst_version_master"}


def read_response(path, raw=None):
    """Returns (document, how) for one saved response, or (None, reason)."""
    if raw is None:
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


def read_request(raw):
    """The JSON the game sent, or None. Requests are encrypted like responses but not compressed."""
    if not raw:
        return None
    try:
        text = raw.decode("utf-8").strip()
        if text[:1] == "{":
            return json.loads(text)
        import base64
        sys.path.insert(0, HERE)
        from fetch_puni_resources import KEY
        from cryptography.hazmat.primitives import padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        text = text.replace("-", "+").replace("_", "/")
        text += "=" * (-len(text) % 4)
        dec = Cipher(algorithms.AES(KEY), modes.ECB()).decryptor()
        unpadder = padding.PKCS7(128).unpadder()
        plain = unpadder.update(dec.update(base64.b64decode(text)) + dec.finalize()) + unpadder.finalize()
        return json.loads(plain[20:].decode("utf-8"))
    except Exception:  # not a game request
        return None


def shape(value):
    """A one-word description of a value's form. Never contains the value itself."""
    if isinstance(value, dict):
        return "table" if "tableData" in value else "data" if "data" in value else "object"
    if isinstance(value, list):
        return "list"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return "text"


def layout(value, depth=4):
    """The structure of a value with every actual value removed: field names, list lengths
    and the column count of table text. Safe to share."""
    if isinstance(value, dict):
        if depth <= 0:
            return "object"
        return {k: layout(v, depth - 1) for k, v in value.items()}
    if isinstance(value, list):
        if not value:
            return "list(0)"
        if depth <= 0:
            return f"list({len(value)})"
        return [f"list({len(value)})", layout(value[0], depth - 1)]
    if isinstance(value, str):
        if "|" in value:
            rows = value.split("*")
            return f"table({len(rows)} rows x {len(rows[0].split('|'))} cols)"
        return "text" if value else "text(empty)"
    return shape(value)


def shape_of_file(text):
    try:
        return shape(json.loads(text))
    except ValueError:
        return "text"


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
    ap.add_argument("captures", help="a mitmproxy save file, or a folder of saved response bodies")
    ap.add_argument("--resources", default="Resources")
    ap.add_argument("--overwrite", action="store_true", help="also replace tables that are not stand-ins")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    ap.add_argument("--shapes", help="also write the field names and forms of every request and response to this "
                                     "file (no values, so nothing personal), for comparing with the emulator")
    ap.add_argument("--quiet", action="store_true", help="do not list every response")
    ap.add_argument("--take", nargs="*", help="replace these fetched tables with the captured copy")
    ap.add_argument("--show", nargs="*", help="print the field layout of these request types, e.g. login gameEnd")
    args = ap.parse_args()

    root = os.path.dirname(os.path.abspath(args.resources))
    list_path = os.path.join(root, "Resources.from-wibwob.list")
    standins = set()
    if os.path.exists(list_path):
        with open(list_path, encoding="utf-8") as f:
            standins = {line.strip()[:-4] for line in f if line.strip().endswith(".txt")}

    variants = {}    # name -> {text: (source, form)}
    shapes = {}
    if os.path.isdir(args.captures):
        sources = [(name, os.path.join(args.captures, name), None, None) for name in sorted(os.listdir(args.captures))
                   if os.path.isfile(os.path.join(args.captures, name))]
    else:
        try:
            sources = [(label, None, body, request) for label, body, request in flow_responses(args.captures)]
        except (ValueError, IndexError):
            # Not a mitmproxy file: treat it as a single saved response
            sources = [(os.path.basename(args.captures), args.captures, None, None)]
        else:
            print(f"mitmproxy file: {len(sources)} game responses")
    files = sources
    requests_seen = {}
    skipped = {}
    sent_empty = set()
    for name, path, body, request_body in sources:
        doc, how = read_response(path, body)
        if not isinstance(doc, dict):
            reason = how if doc is None else "not a response object"
            skipped[name.split(" #")[0]] = reason
            if not args.quiet:
                print(f"  skipped {name}: {reason}")
            continue
        keys = [k for k, v in doc.items() if wanted(k, v)]
        sent_empty.update(k for k, v in doc.items() if v in ("", [], {}) and (k.startswith("ywp_mst_") or k in SETTINGS))
        if not args.quiet:
            print(f"  {name}: {how}, {len(keys)} usable of {len(doc)} keys")
        for key in keys:
            variants.setdefault(key, {}).setdefault(as_text(doc[key]), (name, shape(doc[key])))
        entry = shapes.setdefault(name.split(" #")[0], {"count": 0, "request": {}, "response": {}})
        entry["count"] += 1
        for k, v in doc.items():
            # keep the fullest example of each field
            seen = entry["response"].get(k)
            fresh = layout(v)
            if seen is None or len(json.dumps(fresh)) > len(json.dumps(seen)):
                entry["response"][k] = fresh
        request = read_request(request_body)
        if isinstance(request, dict):
            for k, v in request.items():
                entry["request"][k] = layout(v)

    # A table can arrive in different forms from different requests. The server reads each
    # file in one particular form, so keep the form of the file already there; among the
    # captured copies in that form take the fullest one.
    found = {}
    new, replaced, kept, same, wrong_form, rewrapped = [], [], [], [], [], []
    take = set(args.take or [])
    for key in sorted(variants):
        options = variants[key]
        dest = os.path.join(args.resources, key + ".txt")
        current = None
        if os.path.exists(dest):
            with open(dest, encoding="utf-8") as f:
                current = f.read()
        if current is None:
            text = max(options, key=len)
            found[key] = (text, options[text][0])
            new.append(key)
        else:
            if current in options:
                found[key] = (current, options[current][0])
                same.append(key)
                continue
            form = shape_of_file(current)
            fitting = [t for t, (_, f) in options.items() if f == form]
            if not fitting:
                # Same content, different wrapping: the server keeps some tables inside
                # {"data": [...]} or {"tableData": "..."} where the game sends them bare.
                wrapped = {}
                for t, (source, f) in options.items():
                    if form == "data" and f == "list":
                        wrapped['{"data":' + t + "}"] = (source, form)
                    elif form == "table" and f == "text" and key not in SENT_AS_IS:
                        wrapped[json.dumps({"tableData": t}, ensure_ascii=False, separators=(",", ":"))] = (source, form)
                    elif key in SENT_AS_IS and f == "text":
                        wrapped[t] = (source, f)
                if wrapped:
                    options = wrapped
                    fitting = list(wrapped)
                    rewrapped.append(key)
            if not fitting:
                found[key] = (current, "")
                wrong_form.append((key, form, sorted({f for _, f in options.values()})))
                continue
            text = max(fitting, key=len)
            found[key] = (text, options[text][0])
            if text == current:
                same.append(key)
                continue
            if key in standins or args.overwrite or key in take:
                replaced.append(key)
            else:
                kept.append(key)
                continue
        if not args.dry_run:
            with open(dest, "w", encoding="utf-8") as f:
                f.write(found[key][0])

    print(f"\nresponses read: {len(files)}; tables and settings found: {len(found)}")
    if skipped:
        print(f"responses that are not game data (web pages and the like): {sorted(skipped)}")
    print(f"new files: {len(new)} {new}")
    print(f"replaced ({'stand-ins and others' if args.overwrite else 'Wibble Wobble stand-ins'}): {len(replaced)} {replaced}")
    if rewrapped:
        print(f"re-wrapped into the form the server stores: {sorted(set(rewrapped) & set(new + replaced + kept))}")
    for key in new + replaced:
        choices = len(variants[key])
        if choices > 1:
            print(f"  {key}: {choices} different copies captured; took the fullest, from {found[key][1]}")
    for key, form, seen in wrong_form:
        tag = "stand-in" if key in standins else "fetched"
        print(f"  not replaced: {key} ({tag}) is stored as {form!r} but was only captured as {seen}")
    for name in args.show or []:
        match = next((n for n in shapes if n.lower() == name.lower()), None)
        if not match:
            print(f"--show {name}: no such request in the capture")
            continue
        print(f"--- {match} (captured {shapes[match]['count']} times)")
        print(" request: " + json.dumps(shapes[match]["request"], ensure_ascii=False, sort_keys=True))
        print(" response:")
        for k in sorted(shapes[match]["response"]):
            print(f"   {k}: {json.dumps(shapes[match]['response'][k], ensure_ascii=False)}")
    if args.shapes:
        with open(args.shapes, "w", encoding="utf-8") as f:
            json.dump(shapes, f, ensure_ascii=False, indent=1, sort_keys=True)
        print(f"wrote the field layout of {len(shapes)} request types to {args.shapes}")
    print(f"already identical: {len(same)}")
    if kept:
        print(f"left alone (differs from your fetched copy; --take NAME replaces one, --overwrite all): {len(kept)} {kept}")
    # What the server needs that no capture has supplied yet
    needs_path = os.path.join(HERE, "puniemu_required_resources.txt")
    if os.path.exists(needs_path):
        with open(needs_path, encoding="utf-8") as f:
            needs = [line.strip() for line in f if line.strip()]
        open_items = [n for n in needs if (n.startswith("ywp_mst_") or n in SETTINGS) and n not in found
                      and (n in standins or not os.path.exists(os.path.join(args.resources, n + ".txt")))]
        empty_now = sorted(n for n in open_items if n in sent_empty)
        open_items = [n for n in open_items if n not in sent_empty]
        if empty_now:
            print(f"sent empty by the real server right now (nothing to capture): {' '.join(empty_now)}")
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
