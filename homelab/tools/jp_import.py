"""Import Yo-kai from Japanese Yo-kai Watch Puni Puni into a WibWob Reload server.

The Japanese game server and file server answer without a login. Japanese Yo-kai
art (models, textures, voices) is byte-compatible with the Wibble Wobble 4.0.x
client; only the text needs translating. Run this on the machine that holds the
server files, then rebuild the server image.

Steps:
  1. fetch      download the Japanese tables (once, or to refresh)
       python3 jp_import.py fetch --jp jpdata
  2. list       show Japan-only Yo-kai that can be imported
       python3 jp_import.py list --jp jpdata --resources WWR_BACKUP/Resources [--search 犬] [--rank 6]
  3. translate  (optional) fill in English with Claude; needs ANTHROPIC_API_KEY
       python3 jp_import.py translate --jp jpdata --resources WWR_BACKUP/Resources \
           --translations translations.json --ids 2707000 9000301 ...
     or write translations.json by hand (format: see TEMPLATE below / `template`).
  4. import     add the Yo-kai and download their files (dry run unless --apply)
       python3 jp_import.py import --jp jpdata --resources WWR_BACKUP/Resources \
           --data WWR_BACKUP/dataDownload --translations translations.json --ids ... --apply

Then rebuild:  docker compose up -d --build wibwob
Give one to yourself in game with the admin command:  <PIN> 4 <youkaiId>

Yo-kai above rank SS (7) are imported as SS, because the Wibble Wobble client
has no art or rules for SSS/Z/ZZ/ZZZ/UZ. Yo-kai whose Soultimate type is newer
than the client (types 37+ and 29) are refused unless --allow-new-skill-types.
"""
import argparse
import base64
import datetime
import gzip
import hashlib
import json
import os
import re
import sys
import time
import urllib.request

# ---------------------------------------------------------------- Japanese server

KEY = bytes([0xa8, 0x65, 0xd7, 0xe5, 0xe2, 0x45, 0x8f, 0x8c, 0xe1, 0xb5, 0xec, 0xd0, 0x87, 0xe5, 0x45, 0x94])
SALT = b"0bk2kvtFE2"
GAMESERVER = "https://gameserver.yw-p.com/"
FILESERVER = "https://resource.yw-p.com/eal"
APPSTORE_ID = "1032346221"  # 妖怪ウォッチ ぷにぷに on the Japanese App Store
HEADERS = {"Content-Type": "application/json", "Accept": "application/json", "Accept-Encoding": "identity",
           "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; Pixel 7 Build/TQ3A.230901.001)"}
TABLES = ["ywp_mst_youkai", "ywp_mst_youkai_skill", "ywp_mst_youkai_skill_level",
          "ywp_mst_youkai_view_2d", "ywp_mst_youkai_level", "ywp_mst_version_resource"]


def _aes(encrypt):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    c = Cipher(algorithms.AES(KEY), modes.ECB())
    return c.encryptor() if encrypt else c.decryptor()


def _pkcs7(data, add):
    from cryptography.hazmat.primitives import padding
    p = padding.PKCS7(128).padder() if add else padding.PKCS7(128).unpadder()
    return p.update(data) + p.finalize()


def nhn_call(endpoint, payload):
    body = json.dumps(payload).encode()
    digest = hashlib.sha1(SALT + hashlib.sha1(SALT + b" " + body).digest()).digest()
    e = _aes(True)
    data = base64.urlsafe_b64encode(e.update(_pkcs7(digest + body, True)) + e.finalize())
    req = urllib.request.Request(GAMESERVER + endpoint, data=data, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        text = r.read().decode().strip().replace("-", "+").replace("_", "/")
    text += "=" * (-len(text) % 4)
    d = _aes(False)
    raw = _pkcs7(d.update(base64.b64decode(text)) + d.finalize(), False)
    return json.loads(gzip.decompress(raw[20:]).decode("utf-8"))


def jp_app_version():
    url = f"https://itunes.apple.com/lookup?id={APPSTORE_ID}&country=jp"
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)["results"][0]["version"]


def cmd_fetch(a):
    os.makedirs(a.jp, exist_ok=True)
    version = a.app_version or jp_app_version()
    print(f"Japanese app version {version}")
    res = nhn_call("getMaster.nhn", {"appVer": version, "deviceId": "d-822a61c56b60d03dd373aab9826210e1",
                                     "level5UserId": "0", "osType": 2, "tableNames": "|".join(TABLES),
                                     "userId": "0", "ywpToken": "0", "mstVersionVer": 0})
    if res.get("resultCode") not in (0, None) or res.get("dialogMsg"):
        sys.exit(f"Server refused: {res.get('dialogMsg')!r} (resultCode {res.get('resultCode')}). "
                 f"Pass --app-version with the current Japanese version.")
    for t in TABLES:
        if res.get(t) is None:
            sys.exit(f"Server returned no {t}")
        with open(os.path.join(a.jp, f"{t}.json"), "w", encoding="utf-8") as f:
            json.dump(res[t], f, ensure_ascii=False)
    with open(os.path.join(a.jp, "meta.json"), "w") as f:
        json.dump({"appVer": version, "fetched": datetime.datetime.now(datetime.timezone.utc).isoformat()}, f)
    print(f"Saved {len(TABLES)} tables to {a.jp}")


# ---------------------------------------------------------------- table files

def jp_rows(jp_dir, table):
    with open(os.path.join(jp_dir, f"{table}.json"), encoding="utf-8") as f:
        return [r.split("|") for r in json.load(f)["tableData"].split("*") if r]


class WWTable:
    """A WibWob Reload table file: either {"tableData": "a|b*c|d"} JSON or the raw string."""

    def __init__(self, resources, table):
        self.path = os.path.join(resources, f"{table}.txt")
        with open(self.path, encoding="utf-8-sig") as f:
            self.text = f.read()
        self.wrapper = None
        data = self.text
        try:
            j = json.loads(self.text)
            if isinstance(j, dict) and "tableData" in j:
                self.wrapper, data = j, j["tableData"]
        except ValueError:
            pass
        self.rows = [r.split("|") for r in data.split("*") if r]

    def save(self):
        data = "*".join("|".join(r) for r in self.rows)
        if self.wrapper is not None:
            self.wrapper["tableData"] = data
            out = json.dumps(self.wrapper, ensure_ascii=False)
        else:
            out = data
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(out)


# ---------------------------------------------------------------- selection

def candidates(jp_dir, resources):
    ww_ids = {r[0] for r in WWTable(resources, "ywp_mst_youkai").rows}
    files = {r[1] for r in jp_rows(jp_dir, "ywp_mst_version_resource")}
    skills = {r[0] for r in jp_rows(jp_dir, "ywp_mst_youkai_skill")}
    out = []
    for r in jp_rows(jp_dir, "ywp_mst_youkai"):
        if r[0] in ww_ids or not r[1] or "未使用" in r[1]:
            continue
        if f"{r[0]}.ayd" not in files or r[0] not in skills:
            continue
        out.append(r)
    return out


def known_skill_types(resources):
    """Soultimate types (column 2 of ywp_mst_youkai_skill) the Wibble Wobble client implements."""
    return {r[2] for r in WWTable(resources, "ywp_mst_youkai_skill").rows if len(r) > 2}


def skill_type(jp_dir, ids=None):
    return {r[0]: r[2] for r in jp_rows(jp_dir, "ywp_mst_youkai_skill") if ids is None or r[0] in ids}


def cmd_list(a):
    rows = candidates(a.jp, a.resources)
    known, types = known_skill_types(a.resources), skill_type(a.jp)
    if a.search:
        rows = [r for r in rows if a.search in r[1]]
    if a.rank:
        rows = [r for r in rows if r[3] == str(a.rank)]
    if not a.all:
        rows = [r for r in rows if types.get(r[0]) in known]
    for r in rows:
        safe = "ok " if types.get(r[0]) in known else "NEW"
        print(f"{r[0]}\trank {r[3]:>2}\ttribe {r[4]}\tsoultimate {safe}\t{r[1]}")
    print(f"{len(rows)} importable Yo-kai" + ("" if a.all else " (known Soultimate types only; --all for every one)"),
          file=sys.stderr)


# ---------------------------------------------------------------- text

YK_TEXT = {"name": 1, "description": 15, "befriend1": 16, "befriend2": 17, "befriend3": 18, "befriend4": 19,
           "catchphrase": 20}
SK_TEXT = {"skill_name": 1, "skill_description": 3}


def jp_texts(jp_dir, ids):
    yk = {r[0]: r for r in jp_rows(jp_dir, "ywp_mst_youkai")}
    sk = {r[0]: r for r in jp_rows(jp_dir, "ywp_mst_youkai_skill")}
    lv = {}
    for r in jp_rows(jp_dir, "ywp_mst_youkai_skill_level"):
        lv.setdefault(r[0], []).append(r)
    out = {}
    for i in ids:
        y, s = yk[i], sk.get(i)
        t = {k: y[c] for k, c in YK_TEXT.items()}
        if s:
            t.update({k: s[c] for k, c in SK_TEXT.items()})
        t["skill_levels"] = [r[2] for r in sorted(lv.get(i, []), key=lambda r: int(r[1]))]
        out[i] = t
    return out


def glossary(jp_dir, resources):
    """Official English names for every Yo-kai both versions share, plus a few UI terms."""
    jp = {r[0]: r[1] for r in jp_rows(jp_dir, "ywp_mst_youkai")}
    pairs = [f"{jp[r[0]]} = {r[1]}" for r in WWTable(resources, "ywp_mst_youkai").rows
             if r[0] in jp and jp[r[0]] != r[1] and "未使用" not in jp[r[0]]]
    terms = ["妖怪ぷに / ぷに = Wib Wob", "消す数 = Pop", "いりょく = Wib Wob (as in 'Wib Wob: 72pt')",
             "ひっさつわざ = Soultimate", "ともだち = friend", "妖怪 = Yo-kai", "ガシャ = Crank-a-kai",
             "Ｙマネー = Y-Money", "イサマシ族 = Brave", "フシギ族 = Mysterious", "ゴーケツ族 = Tough",
             "プリチー族 = Charming", "ポカポカ族 = Heartful", "ウスラカゲ族 = Shady", "ブキミー族 = Eerie",
             "ニョロロン族 = Slippery"]
    return "\n".join(terms + pairs)


TEMPLATE = {"<youkaiId>": {"name": "English name (max 20 chars)", "description": "...", "befriend1": "...",
                           "befriend2": "...", "befriend3": "...", "befriend4": "...", "catchphrase": "...",
                           "skill_name": "...", "skill_description": "...", "skill_levels": ["Lv1 text", "..."]}}


def load_translations(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def cmd_template(a):
    texts = jp_texts(a.jp, a.ids)
    existing = load_translations(a.translations)
    for i, t in texts.items():
        existing.setdefault(i, {"_japanese": t, **{k: "" for k in t if k != "skill_levels"},
                                "skill_levels": ["" for _ in t["skill_levels"]]})
    with open(a.translations, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    print(f"Wrote {a.translations}: fill in the English fields (the Japanese is under _japanese)")


def cmd_translate(a):
    import anthropic  # pip install anthropic

    texts = jp_texts(a.jp, a.ids)
    out = load_translations(a.translations)
    todo = [i for i in a.ids if not out.get(i, {}).get("name")]
    if not todo:
        print("Everything requested is already translated.")
        return
    client = anthropic.Anthropic()
    system = [{"type": "text",
               "text": ("You translate Japanese text from the mobile game Yo-kai Watch Puni Puni into the English "
                        "of its US release, Yo-kai Watch Wibble Wobble. Use official English Yo-kai names where "
                        "they exist (glossary below; otherwise the Yo-kai Watch 2/3/Blasters localisation if you "
                        "know it), and otherwise invent a playful English name in the same punny style. Rules: "
                        "names at most 20 characters; keep every \\n line break position roughly the same and "
                        "keep each line under 26 characters; keep the ▽ marker and any <R>...</R> tags exactly; "
                        "keep numbers, ranges like 7～8 and 'pt' unchanged; if a source string is empty or '0', "
                        "return it unchanged; a catchphrase of 'なし' (none) becomes '0'.\n\nGlossary:\n" + glossary(a.jp, a.resources)),
               "cache_control": {"type": "ephemeral"}}]
    item = {"type": "object", "additionalProperties": False,
            "properties": {"id": {"type": "string"}, **{k: {"type": "string"} for k in list(YK_TEXT) + list(SK_TEXT)},
                           "skill_levels": {"type": "array", "items": {"type": "string"}}},
            "required": ["id"] + list(YK_TEXT) + list(SK_TEXT) + ["skill_levels"]}
    schema = {"type": "object", "additionalProperties": False,
              "properties": {"items": {"type": "array", "items": item}}, "required": ["items"]}

    for start in range(0, len(todo), a.batch):
        batch = todo[start:start + a.batch]
        payload = {i: texts[i] for i in batch}
        resp = client.messages.create(
            model=a.model, max_tokens=16000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
            system=system,
            messages=[{"role": "user", "content": "Translate each Yo-kai's fields. Return one item per id.\n\n"
                                                  + json.dumps(payload, ensure_ascii=False)}],
        )
        if resp.stop_reason == "refusal":
            print(f"  batch {batch} refused ({resp.stop_details.category if resp.stop_details else '?'}); skipped")
            continue
        if resp.stop_reason == "max_tokens":
            print(f"  batch {batch} hit max_tokens; retry with a smaller --batch")
            continue
        text = next(b.text for b in resp.content if b.type == "text")
        for it in json.loads(text)["items"]:
            i = it.pop("id")
            if i in payload:
                out[i] = it
        with open(a.translations, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"  translated {start + len(batch)}/{len(todo)}")
        time.sleep(0.2)
    print(f"Saved {a.translations}")


# ---------------------------------------------------------------- import

def cmd_import(a):
    tr = load_translations(a.translations)
    ids = list(dict.fromkeys(a.ids))
    importable = {r[0]: r for r in candidates(a.jp, a.resources)}
    problems = [i for i in ids if i not in importable]
    if problems:
        sys.exit(f"Not importable (already on the server, no art bundle, or unknown): {' '.join(problems)}")
    known, types = known_skill_types(a.resources), skill_type(a.jp, set(ids))
    risky = [f"{i} (type {types.get(i)})" for i in ids if types.get(i) not in known]
    if risky and not a.allow_new_skill_types:
        sys.exit("These use Soultimate types the Wibble Wobble client was never built with, so their Soultimate "
                 "will probably fail or crash: " + ", ".join(risky) + ". Leave them out, or pass "
                 "--allow-new-skill-types to try anyway.")
    missing = [i for i in ids if not tr.get(i, {}).get("name")]
    if missing and not a.allow_japanese:
        sys.exit(f"No English translation for: {' '.join(missing)}. Run `translate`/`template`, "
                 f"or pass --allow-japanese (the client's font may not show Japanese).")

    jp_sk = {r[0]: r for r in jp_rows(a.jp, "ywp_mst_youkai_skill")}
    jp_lv = {}
    for r in jp_rows(a.jp, "ywp_mst_youkai_skill_level"):
        jp_lv.setdefault(r[0], []).append(r)
    jp_art = {r[0]: r for r in jp_rows(a.jp, "ywp_mst_youkai_view_2d")}
    jp_res = jp_rows(a.jp, "ywp_mst_version_resource")

    yk = WWTable(a.resources, "ywp_mst_youkai")
    sk = WWTable(a.resources, "ywp_mst_youkai_skill")
    lv = WWTable(a.resources, "ywp_mst_youkai_skill_level")
    art = WWTable(a.resources, "ywp_mst_youkai_view_2d")
    lvl = WWTable(a.resources, "ywp_mst_youkai_level")
    res = WWTable(a.resources, "ywp_mst_version_resource")
    ww_cols = max(set(len(r) for r in yk.rows), key=[len(r) for r in yk.rows].count)
    have_files = {r[1] for r in res.rows}
    have_levels = {(r[0], r[1]) for r in lvl.rows}
    next_res_id = max(int(r[0]) for r in res.rows if r[0].isdigit()) + 1
    today = datetime.date.today().strftime("%Y%m%d")
    changed = set()
    downloads = []

    for i in ids:
        t = tr.get(i, {})
        row = importable[i][:ww_cols]
        for k, c in YK_TEXT.items():
            if t.get(k):
                row[c] = t[k]
        if row[YK_TEXT["catchphrase"]] == "なし":   # "none"; Wibble Wobble writes 0
            row[YK_TEXT["catchphrase"]] = "0"
        if int(row[3]) > 7:
            row[3] = "7"
        yk.rows.append(row); changed.add("ywp_mst_youkai")

        if i in jp_sk:
            s = list(jp_sk[i])
            for k, c in SK_TEXT.items():
                if t.get(k):
                    s[c] = t[k]
            sk.rows.append(s); changed.add("ywp_mst_youkai_skill")
        for n, l in enumerate(sorted(jp_lv.get(i, []), key=lambda r: int(r[1]))):
            l = list(l)
            if n < len(t.get("skill_levels", [])) and t["skill_levels"][n]:
                l[2] = t["skill_levels"][n]
            lv.rows.append(l); changed.add("ywp_mst_youkai_skill_level")
        key = f"art_{i}.png"
        if key in jp_art and key not in {r[0] for r in art.rows}:
            art.rows.append(list(jp_art[key])); changed.add("ywp_mst_youkai_view_2d")

        level_type = importable[i][5]
        for r in jp_rows(a.jp, "ywp_mst_youkai_level"):
            if r[0] == level_type and (r[0], r[1]) not in have_levels:
                lvl.rows.append(r); have_levels.add((r[0], r[1])); changed.add("ywp_mst_youkai_level")

        # Files: anything named after this Yo-kai, plus the Soultimate effect files it references
        refs = set()
        if i in jp_sk:
            refs |= {jp_sk[i][6] + ".ez", jp_sk[i][6], jp_sk[i][7]}
        for r in jp_res:
            name = r[1]
            if name in have_files:
                continue
            if re.search(rf"(?<!\d){i}(?!\d)", name) or name in refs:
                downloads.append(r); have_files.add(name)

    for r in downloads:
        res.rows.append([str(next_res_id), r[1], r[2], today, "1", "4.0.6", r[6] if len(r) > 6 else ""])
        next_res_id += 1
    if downloads:
        changed.add("ywp_mst_version_resource")

    total_kb = sum(int(r[6]) for r in downloads if len(r) > 6 and r[6].isdigit()) // 1024
    print(f"{len(ids)} Yo-kai, {len(downloads)} files (~{total_kb} KB), tables: {', '.join(sorted(changed))}")
    for i in ids:
        print(f"  {i}  {tr.get(i, {}).get('name') or importable[i][1]}  (rank {min(int(importable[i][3]), 7)})")
    if not a.apply:
        print("Dry run. Re-run with --apply to write the files.")
        return

    target = os.path.join(a.data, "4.0.6", today)
    os.makedirs(target, exist_ok=True)
    for n, r in enumerate(downloads, 1):
        dest = os.path.join(target, r[1])
        if not os.path.exists(dest):
            url = f"{FILESERVER}/{r[5]}/{r[3]}/{r[1]}"
            with urllib.request.urlopen(url, timeout=120) as resp, open(dest + ".part", "wb") as f:
                f.write(resp.read())
            os.replace(dest + ".part", dest)
        if n % 25 == 0:
            print(f"  downloaded {n}/{len(downloads)}")

    for tbl in (yk, sk, lv, art, lvl, res):
        tbl.save()
    bump_versions(a.resources, changed)
    print("Done. Rebuild the server: docker compose up -d --build wibwob")


def bump_versions(resources, tables):
    """Raise the master-data version so phones download the changed tables again."""
    p = os.path.join(resources, "mstVersionMaster.txt")
    with open(p, encoding="utf-8-sig") as f:
        v = int(f.read().strip())
    with open(p, "w", encoding="utf-8") as f:
        f.write(str(v + 1))
    vm = WWTable(resources, "ywp_mst_version_master")
    for r in vm.rows:
        if r[0] in tables and len(r) > 1 and r[1].isdigit():
            r[1] = str(int(r[1]) + 1)
    vm.save()
    print(f"Master data version {v} -> {v + 1}")


# ---------------------------------------------------------------- CLI

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch"); f.add_argument("--jp", required=True); f.add_argument("--app-version")
    l = sub.add_parser("list")
    for s in (l,):
        s.add_argument("--jp", required=True); s.add_argument("--resources", required=True)
    l.add_argument("--search"); l.add_argument("--rank", type=int); l.add_argument("--all", action="store_true")
    t = sub.add_parser("translate")
    t.add_argument("--jp", required=True); t.add_argument("--resources", required=True)
    t.add_argument("--translations", required=True); t.add_argument("--ids", nargs="+", required=True)
    t.add_argument("--model", default="claude-haiku-5-5"); t.add_argument("--batch", type=int, default=8)
    m = sub.add_parser("template")
    m.add_argument("--jp", required=True); m.add_argument("--translations", required=True)
    m.add_argument("--ids", nargs="+", required=True)
    i = sub.add_parser("import")
    i.add_argument("--jp", required=True); i.add_argument("--resources", required=True)
    i.add_argument("--data", required=True); i.add_argument("--translations")
    i.add_argument("--ids", nargs="+", required=True); i.add_argument("--apply", action="store_true")
    i.add_argument("--allow-japanese", action="store_true"); i.add_argument("--allow-new-skill-types", action="store_true")
    a = p.parse_args()
    {"fetch": cmd_fetch, "list": cmd_list, "translate": cmd_translate, "template": cmd_template,
     "import": cmd_import}[a.cmd](a)


if __name__ == "__main__":
    main()
