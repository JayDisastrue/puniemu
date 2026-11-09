"""Port Yo-kai from Japanese Yo-kai Watch Puni Puni into a WibWob Reload server.

The Japanese game server and file server answer without a login. Japanese Yo-kai
art (models, textures, voices) loads in the Wibble Wobble 4.0.x client as-is;
the text needs English, and two things need adapting:

  * Ranks: the client only knows up to SS. Higher ranks (SSS..UZ+) become SS and
    their stats are rescaled into the top of Wibble Wobble's SS range, keeping
    their order (a Japanese UZ+ ends up stronger than a Japanese SSS).
  * Soultimates: about 30% use a type the 2017 client implements and come over
    unchanged. The rest use mechanics the client has no code for, so they get a
    stand-in: the mechanics, effects and English description of the closest
    matching Soultimate the client does know (matched on what the move does).
    The Soultimate keeps its own (translated) name.

Run on the machine holding the server files, then rebuild the server image.

  1. fetch       python3 jp_import.py fetch --jp jpdata
  2. list        python3 jp_import.py list --jp jpdata --resources WWR_BACKUP/Resources
  3. translate   python3 jp_import.py translate --jp jpdata --resources WWR_BACKUP/Resources \\
                     --translations translations.json --all
                 Uses Claude Code (`claude -p`, your Claude plan) by default; resumable,
                 just run it again after a usage limit. --engine api uses ANTHROPIC_API_KEY.
  4. import      python3 jp_import.py import --jp jpdata --resources WWR_BACKUP/Resources \\
                     --data WWR_BACKUP/dataDownload --translations translations.json --all \\
                     [--gacha 500055] --apply
  5. rebuild     docker compose up -d --build wibwob

Give one to yourself in game with the admin command:  <PIN> 4 <youkaiId>
"""
import argparse
import base64
import concurrent.futures
import datetime
import gzip
import hashlib
import json
import os
import re
import subprocess
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


JAPANESE = re.compile(r"[぀-ヿ一-鿿０-９Ａ-Ｚａ-ｚ]")
MAX_RANK = 7       # SS: the highest rank the Wibble Wobble client has art and rules for
YK = {"name": 1, "rank": 3, "level_type": 5, "base_hp": 8, "max_hp": 9, "base_atk": 10, "max_atk": 11,
      "description": 15, "befriend": (16, 17, 18, 19), "catchphrase": 20}
SK = {"name": 1, "type": 2, "description": 3, "effect": 6, "dat": 7}


def grouped(rows):
    out = {}
    for r in rows:
        out.setdefault(r[0], []).append(r)
    for v in out.values():
        v.sort(key=lambda r: int(r[1]) if r[1].isdigit() else 0)
    return out


# ---------------------------------------------------------------- what to import

class Catalog:
    """Everything needed to decide how each Japanese Yo-kai is ported."""

    def __init__(self, jp_dir, resources):
        self.jp_dir, self.resources = jp_dir, resources
        self.ww_yk = WWTable(resources, "ywp_mst_youkai")
        self.ww_ids = {r[0] for r in self.ww_yk.rows}
        self.ww_sk = {r[0]: r for r in WWTable(resources, "ywp_mst_youkai_skill").rows}
        self.ww_lv = grouped(WWTable(resources, "ywp_mst_youkai_skill_level").rows)
        self.known_types = {r[SK["type"]] for r in self.ww_sk.values() if len(r) > SK["type"]}
        self.jp_yk = {r[0]: r for r in jp_rows(jp_dir, "ywp_mst_youkai")}
        self.jp_sk = {r[0]: r for r in jp_rows(jp_dir, "ywp_mst_youkai_skill")}
        self.jp_lv = grouped(jp_rows(jp_dir, "ywp_mst_youkai_skill_level"))
        self.jp_res = jp_rows(jp_dir, "ywp_mst_version_resource")
        self.jp_files = {r[1] for r in self.jp_res}
        self.ww_tribe = {r[0]: r[4] for r in self.ww_yk.rows if len(r) > 4}
        self._donors = None
        self._bands = None

    def ww_name(self, i):
        return next((r[YK["name"]] for r in self.ww_yk.rows if r[0] == i), i)

    def eligible(self):
        out = []
        for i, r in self.jp_yk.items():
            if i in self.ww_ids or not r[YK["name"]] or "未使用" in r[YK["name"]] or "専用" in r[YK["name"]]:
                continue
            if not r[YK["rank"]].isdigit() or int(r[YK["rank"]]) < 1:
                continue
            if not (r[YK["max_hp"]].isdigit() and int(r[YK["max_hp"]]) > 0 and
                    r[YK["max_atk"]].isdigit() and int(r[YK["max_atk"]]) > 0):
                continue
            if f"{i}.ayd" not in self.jp_files or i not in self.jp_sk or i not in self.jp_lv:
                continue
            out.append(i)
        return out

    def native(self, i):
        """True if the client can run this Yo-kai's own Soultimate: known type, single (pre-cut-in) effect."""
        s = self.jp_sk[i]
        return s[SK["type"]] in self.known_types and "&" not in s[SK["effect"]]

    # -- stand-in Soultimates
    TAGS = {
        "center": r"中央", "line": r"縦|横|一線|一列|列", "allpop": r"全消し", "single": r"1匹|１匹|1体|１体|単体|一体",
        "allfoe": r"全体|敵すべて|すべての敵|全員", "heal": r"回復", "atkup": r"攻撃力|こうげきりょく",
        "guard": r"ダメージを(へら|カット|軽減)|へらす|守", "orb": r"玉", "bonus": r"ボーナス", "big": r"でかぷに|巨大",
        "stall": r"さぼら|動きを止|しびれ", "fever": r"フィーバー", "tap": r"タップ", "time": r"一定時間|しばらく",
        "random": r"ランダム|バラバラ", "pop": r"消す|消し", "damage": r"ダメージ|攻撃",
        "hp": r"HP|ＨＰ", "combo": r"コンボ", "transform": r"変化|変え", "sames": r"同じ"}

    def _tags(self, text):
        return {k for k, p in self.TAGS.items() if re.search(p, text)}

    @staticmethod
    def _grams(text):
        s = re.sub(r"[\s　（）()、。0-9０-９%％]", "", text)
        return {s[i:i + 2] for i in range(len(s) - 1)}

    def donors(self):
        """Wibble Wobble Soultimates usable as stand-ins: known type, English text, level rows present."""
        if self._donors is None:
            self._donors = []
            for i, ww in self.ww_sk.items():
                jp = self.jp_sk.get(i)
                lv = self.ww_lv.get(i)
                if not jp or not lv or ww[SK["type"]] not in self.known_types:
                    continue
                if JAPANESE.search(ww[SK["description"]]) or any(JAPANESE.search(r[2]) for r in lv):
                    continue
                d = jp[SK["description"]]
                self._donors.append((self._tags(d), self._grams(d), i))
        return self._donors

    def standin(self, i):
        """Closest Soultimate by what it does; among near-ties prefer the same tribe, then spread evenly."""
        desc = self.jp_sk[i][SK["description"]]
        tags, grams = self._tags(desc), self._grams(desc)

        def score(d):
            return len(tags & d[0]) - 0.5 * len(d[0] - tags) + len(grams & d[1]) / max(1, len(grams | d[1]))

        scored = [(score(d), d[2]) for d in self.donors()]
        top = max(sc for sc, _ in scored)
        near = sorted(d for sc, d in scored if sc >= top - 0.35)
        tribe = self.jp_yk[i][4]
        same = [d for d in near if self.ww_tribe.get(d) == tribe]
        pool = same or near
        return pool[int(hashlib.md5(i.encode()).hexdigest(), 16) % len(pool)]

    # -- stats for ranks above SS
    def bands(self):
        if self._bands is None:
            ss = [r for r in self.ww_yk.rows if r[YK["rank"]] == str(MAX_RANK)]
            self._bands = {}
            for col in ("max_hp", "max_atk"):
                v = sorted(int(r[YK[col]]) for r in ss if r[YK[col]].isdigit() and int(r[YK[col]]) > 0)
                p90, top = v[len(v) * 9 // 10], int(v[-1] * 1.15)
                per_rank = {}
                for r in self.jp_yk.values():
                    if r[YK["rank"]].isdigit() and int(r[YK["rank"]]) > MAX_RANK and r[YK[col]].isdigit() \
                            and int(r[YK[col]]) > 0:
                        per_rank.setdefault(int(r[YK["rank"]]), []).append(int(r[YK[col]]))
                ranks = sorted(per_rank)
                self._bands[col] = (p90, top, ranks, {k: sorted(v) for k, v in per_rank.items()})
        return self._bands

    def rebalanced(self, row):
        """Ranks above SS: rescale HP/ATK into the top of the SS band, keeping their order."""
        rank = int(row[YK["rank"]])
        if rank <= MAX_RANK:
            return row
        row = list(row)
        for max_col, base_col in (("max_hp", "base_hp"), ("max_atk", "base_atk")):
            p90, top, ranks, per_rank = self.bands()[max_col]
            values = per_rank[rank]
            value = int(row[YK[max_col]])
            pct = sum(1 for x in values if x <= value) / len(values)
            slot = ranks.index(rank)
            lo = p90 + (top - p90) * slot / len(ranks)
            hi = p90 + (top - p90) * (slot + 1) / len(ranks)
            target = lo + (hi - lo) * pct
            factor = target / value
            row[YK[max_col]] = str(round(target))
            if row[YK[base_col]].isdigit():
                row[YK[base_col]] = str(max(1, round(int(row[YK[base_col]]) * factor)))
        row[YK["rank"]] = str(MAX_RANK)
        return row


# ---------------------------------------------------------------- text

LEVEL_TERMS = [("玉のいりょく:", "Ball: "), ("目安のいりょく:", "Power: ~"), ("いりょく:", "Power: "),
               ("消す数:", "Pop: "), ("回復力:", "Heal: "), ("フィーバー強化:", "Fever: "), ("効果度:", "Effect: "),
               ("効果時間:", "Time: "), ("ボーナス玉の数:", "Orbs: "), ("必要わざゲージ:", "Gauge: "),
               ("でかぷにのサイズ:", "Big Wob size: "), ("ダメージ:", "Damage: "), ("秒", "s"), ("　", " ")]


def level_by_rule(text):
    for jp, en in LEVEL_TERMS:
        text = text.replace(jp, en)
    return None if JAPANESE.search(text) else text


def needed_text(cat, i):
    """The Japanese strings this Yo-kai still needs in English."""
    y, s = cat.jp_yk[i], cat.jp_sk[i]
    befriend = list(dict.fromkeys(y[c] for c in YK["befriend"] if y[c]))
    t = {"name": y[YK["name"]], "description": y[YK["description"]], "befriend": befriend,
         "catchphrase": "" if y[YK["catchphrase"]] in ("なし", "0", "") else y[YK["catchphrase"]],
         "skill_name": s[SK["name"]], "skill_description": "", "skill_levels": []}
    if cat.native(i):
        t["skill_description"] = s[SK["description"]]
        t["skill_levels"] = list(dict.fromkeys(r[2] for r in cat.jp_lv[i] if level_by_rule(r[2]) is None))
    return t


def glossary(cat):
    pairs = [f"{cat.jp_yk[r[0]][1]} = {r[1]}" for r in cat.ww_yk.rows
             if r[0] in cat.jp_yk and cat.jp_yk[r[0]][1] != r[1] and not JAPANESE.search(r[1])]
    terms = ["妖怪ぷに / ぷに = Wib Wob", "でかぷに = Big Wob", "ひっさつわざ = Soultimate", "妖怪 = Yo-kai",
             "ガシャ = Crank-a-kai", "Ｙマネー = Y-Money", "フィーバー = Fever", "イサマシ族 = Brave",
             "フシギ族 = Mysterious", "ゴーケツ族 = Tough", "プリチー族 = Charming", "ポカポカ族 = Heartful",
             "ウスラカゲ族 = Shady", "ブキミー族 = Eerie", "ニョロロン族 = Slippery", "覚醒 = Awakened"]
    return "\n".join(terms + pairs)


INSTRUCTIONS = (
    "You translate Japanese text from the mobile game Yo-kai Watch Puni Puni into the English of its US "
    "release, Yo-kai Watch Wibble Wobble. Use official English Yo-kai names where they exist (glossary below; "
    "otherwise the Yo-kai Watch 2/3/4/Blasters localisation if you know it), otherwise invent a playful English "
    "name in the same punny style. Crossover characters from other franchises keep their official English names. "
    "Rules: names at most 20 characters; keep every \\n line break position roughly the same and each line under "
    "26 characters; keep ▽ markers and <R>...</R> tags exactly; keep numbers, ranges like 7～8 and 'pt' "
    "unchanged; return empty strings and empty lists unchanged. Translate every string inside each list, in "
    "order.")

ITEM_KEYS = ["name", "description", "befriend", "catchphrase", "skill_name", "skill_description", "skill_levels"]
ITEM_SCHEMA = {"type": "object", "additionalProperties": False,
               "properties": {"id": {"type": "string"},
                              **{k: ({"type": "array", "items": {"type": "string"}} if k in ("befriend", "skill_levels")
                                     else {"type": "string"}) for k in ITEM_KEYS}},
               "required": ["id"] + ITEM_KEYS}
SCHEMA = {"type": "object", "additionalProperties": False,
          "properties": {"items": {"type": "array", "items": ITEM_SCHEMA}}, "required": ["items"]}


class UsageLimit(Exception):
    pass


def engine_claude_code(system, user, model):
    """One `claude -p` call: uses the signed-in Claude plan, no API key."""
    prompt = (f"{system}\n\n{user}\n\nReply with only a JSON object of the form "
              f'{{"items": [{{"id": "...", ' + ", ".join(f'"{k}": ...' for k in ITEM_KEYS) + "}]}}, "
              "with no other text and no code fences.")
    cmd = ["claude", "-p", "--output-format", "json"] + (["--model", model] if model else [])
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        sys.exit("`claude` not found. Install Claude Code on this machine and sign in (run `claude` once), "
                 "or use --engine api with ANTHROPIC_API_KEY.")
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        if re.search(r"(?i)usage limit|rate limit|limit reached|quota", out):
            raise UsageLimit(out.strip()[:300])
        raise RuntimeError(f"claude exited {p.returncode}: {out.strip()[:300]}")
    try:
        result = json.loads(p.stdout)
        text = result.get("result", "") if isinstance(result, dict) else p.stdout
        if isinstance(result, dict) and result.get("is_error"):
            if re.search(r"(?i)usage limit|rate limit|limit reached", text):
                raise UsageLimit(text[:300])
            raise RuntimeError(text[:300])
    except ValueError:
        text = p.stdout
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise RuntimeError(f"no JSON in reply: {text[:200]}")
    return json.loads(m.group())


def engine_api(system, user, model):
    import anthropic  # pip install anthropic
    client = engine_api.client = getattr(engine_api, "client", None) or anthropic.Anthropic()
    try:
        resp = client.messages.create(
            model=model or "claude-haiku-5-5", max_tokens=16000,
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}])
    except anthropic.RateLimitError as e:
        raise UsageLimit(str(e)) from e
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refused ({resp.stop_details.category if resp.stop_details else '?'})")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("hit max_tokens; use a smaller --batch")
    return json.loads(next(b.text for b in resp.content if b.type == "text"))


def load_translations(path):
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def is_translated(entry, need):
    if not entry or not entry.get("name"):
        return False
    if "befriend1" in entry:            # older hand-written layout: befriend1..4 + full skill_levels list
        return True
    return (len(entry.get("befriend", [])) == len(need["befriend"]) and
            len(entry.get("skill_levels", [])) == len(need["skill_levels"]))


def select_ids(cat, a):
    ids = cat.eligible() if a.all else list(dict.fromkeys(a.ids or []))
    if getattr(a, "native_only", False):
        ids = [i for i in ids if cat.native(i)]
    if getattr(a, "limit", None):
        ids = ids[:a.limit]
    return ids


def cmd_translate(a):
    cat = Catalog(a.jp, a.resources)
    ids = select_ids(cat, a)
    out = load_translations(a.translations)
    needs = {i: needed_text(cat, i) for i in ids}
    todo = [i for i in ids if not is_translated(out.get(i), needs[i])]
    print(f"{len(ids) - len(todo)} already translated, {len(todo)} to go ({a.engine})")
    engine = engine_claude_code if a.engine == "claude-code" else engine_api
    system = INSTRUCTIONS + "\n\nGlossary:\n" + glossary(cat)
    failed = []
    for start in range(0, len(todo), a.batch):
        batch = todo[start:start + a.batch]
        payload = {i: needs[i] for i in batch}
        user = "Translate each Yo-kai's fields. Return one item per id.\n\n" + json.dumps(payload, ensure_ascii=False)
        try:
            items = engine(system, user, a.model)["items"]
        except UsageLimit as e:
            print(f"Stopped: usage limit reached ({e}). Progress is saved; run the same command again later.")
            break
        except Exception as e:                                   # noqa: BLE001 - keep going, report at end
            print(f"  batch starting {batch[0]} failed: {e}")
            failed += batch
            continue
        for it in items:
            i = str(it.pop("id", ""))
            if i in payload:
                need = payload[i]
                it["befriend"] = (it.get("befriend") or [])[:len(need["befriend"])]
                it["skill_levels"] = (it.get("skill_levels") or [])[:len(need["skill_levels"])]
                it["_source"] = {"befriend": need["befriend"], "skill_levels": need["skill_levels"]}
                out[i] = it
        save_json(a.translations, out)
        print(f"  {min(start + a.batch, len(todo))}/{len(todo)}")
    if failed:
        print(f"{len(failed)} Yo-kai failed; run again to retry them.")
    print(f"Saved {a.translations}")


def english_for(cat, i, t):
    """Combine a translation entry with the Japanese row: befriend lines by source, levels by rule or translation."""
    y = cat.jp_yk[i]
    if "befriend1" in t:                # older hand-written layout
        befriend = [t.get(f"befriend{n}") or y[c] for n, c in enumerate(YK["befriend"], 1)]
        given = t.get("skill_levels", [])
        levels = [given[n] if n < len(given) and given[n] else (level_by_rule(r[2]) or r[2])
                  for n, r in enumerate(cat.jp_lv[i])]
        return befriend, levels
    src = t.get("_source", {})
    bf_map = dict(zip(src.get("befriend", []), t.get("befriend", [])))
    befriend = [bf_map.get(y[c], y[c]) for c in YK["befriend"]]
    lv_map = dict(zip(src.get("skill_levels", []), t.get("skill_levels", [])))
    levels = [level_by_rule(r[2]) or lv_map.get(r[2], r[2]) for r in cat.jp_lv[i]]
    return befriend, levels


# ---------------------------------------------------------------- import

def resource_index(cat):
    idx = {}
    for r in cat.jp_res:
        for n in set(re.findall(r"(?<!\d)\d{7}(?!\d)", r[1])):
            idx.setdefault(n, []).append(r)
    return idx


def download(rows, target, workers=8):
    """Fetch files into target (skipping existing ones); return the names that failed."""
    os.makedirs(target, exist_ok=True)

    def one(r):
        dest = os.path.join(target, r[1])
        if os.path.exists(dest):
            return None
        url = f"{FILESERVER}/{r[5]}/{r[3]}/{r[1]}"
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=120) as resp, open(dest + ".part", "wb") as f:
                    f.write(resp.read())
                os.replace(dest + ".part", dest)
                return None
            except Exception:                                    # noqa: BLE001
                time.sleep(2 * (attempt + 1))
        return r[1]

    failed, done = [], 0
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        for res in pool.map(one, rows):
            done += 1
            if res:
                failed.append(res)
            if done % 250 == 0:
                print(f"  downloaded {done}/{len(rows)}")
    return set(failed)


def cmd_import(a):
    cat = Catalog(a.jp, a.resources)
    tr = load_translations(a.translations)
    ids = select_ids(cat, a)
    eligible = set(cat.eligible())
    bad = [i for i in ids if i not in eligible]
    if bad:
        sys.exit(f"Not importable (already on the server, no art bundle, a placeholder, or unknown): {' '.join(bad)}")
    needs = {i: needed_text(cat, i) for i in ids}
    untranslated = [i for i in ids if not is_translated(tr.get(i), needs[i])]
    if untranslated and not a.allow_japanese:
        if a.all:
            ids = [i for i in ids if i not in untranslated]
            print(f"Skipping {len(untranslated)} Yo-kai with no English yet (run `translate`).")
        else:
            sys.exit(f"No English for: {' '.join(untranslated[:20])}{' ...' if len(untranslated) > 20 else ''}. "
                     f"Run `translate`, or pass --allow-japanese (the client's font may not show Japanese).")
    if not ids:
        sys.exit("Nothing to import.")

    yk = WWTable(a.resources, "ywp_mst_youkai")
    sk = WWTable(a.resources, "ywp_mst_youkai_skill")
    lv = WWTable(a.resources, "ywp_mst_youkai_skill_level")
    art = WWTable(a.resources, "ywp_mst_youkai_view_2d")
    lvl = WWTable(a.resources, "ywp_mst_youkai_level")
    res = WWTable(a.resources, "ywp_mst_version_resource")
    ww_cols = max(set(len(r) for r in yk.rows), key=[len(r) for r in yk.rows].count)
    have_files = {r[1] for r in res.rows}
    have_levels = {(r[0], r[1]) for r in lvl.rows}
    have_art = {r[0] for r in art.rows}
    jp_art = {r[0]: r for r in jp_rows(a.jp, "ywp_mst_youkai_view_2d")}
    jp_levels = jp_rows(a.jp, "ywp_mst_youkai_level")
    by_id = resource_index(cat)
    jp_by_name = {r[1]: r for r in cat.jp_res}

    # Work out every file first, so a Yo-kai whose bundle fails to download is left out cleanly
    plan, want = {}, {}
    for i in ids:
        native = cat.native(i)
        files = []
        for r in by_id.get(i, []):
            if r[1] in have_files or (not native and r[1].startswith("skill_")):
                continue
            files.append(r)
        if native:
            s = cat.jp_sk[i]
            for name in (s[SK["effect"]] + ".ez", s[SK["dat"]]):
                if name in jp_by_name and name not in have_files:
                    files.append(jp_by_name[name])
        plan[i] = (native, files)
        for r in files:
            want[r[1]] = r

    standins = {i: cat.standin(i) for i in ids if not plan[i][0]}
    total_kb = sum(int(r[6]) for r in want.values() if len(r) > 6 and r[6].isdigit()) // 1024
    native_n = sum(1 for i in ids if plan[i][0])
    print(f"{len(ids)} Yo-kai: {native_n} with their own Soultimate, {len(ids) - native_n} with a stand-in; "
          f"{sum(1 for i in ids if int(cat.jp_yk[i][YK['rank']]) > MAX_RANK)} above SS rescaled to SS")
    print(f"{len(want)} files to download (~{total_kb / 1024:.0f} MB)")
    for i in ids[:a.show]:
        t = tr.get(i, {})
        how = "own Soultimate" if plan[i][0] else f"stand-in: {cat.ww_name(standins[i])}'s"
        print(f"  {i}  {t.get('name') or cat.jp_yk[i][1]}  rank {min(int(cat.jp_yk[i][YK['rank']]), MAX_RANK)}  ({how})")
    if len(ids) > a.show:
        print(f"  ... and {len(ids) - a.show} more")
    if not a.apply:
        print("Dry run. Re-run with --apply to download and write.")
        return

    today = datetime.date.today().strftime("%Y%m%d")
    target = os.path.join(a.data, "4.0.6", today)
    failed = set() if a.skip_download else download(list(want.values()), target, a.workers)
    if failed:
        print(f"{len(failed)} files failed to download; those are left out (run again to retry).")

    next_res_id = max(int(r[0]) for r in res.rows if r[0].isdigit()) + 1
    # Some of these Yo-kai already have untranslated leftover Soultimate rows (from events whose Yo-kai
    # were never added); replace those so each Yo-kai ends up with exactly one, in English.
    replacing = set(ids) & ({r[0] for r in sk.rows} | {r[0] for r in lv.rows})
    if replacing:
        sk.rows = [r for r in sk.rows if r[0] not in replacing]
        lv.rows = [r for r in lv.rows if r[0] not in replacing]
    added, skipped = [], []
    for i in ids:
        native, files = plan[i]
        if f"{i}.ayd" in failed:
            skipped.append(i)
            continue
        t = tr.get(i, {})
        befriend, levels = english_for(cat, i, t)
        row = cat.rebalanced(cat.jp_yk[i])[:ww_cols]
        if t.get("name"):
            row[YK["name"]] = t["name"]
        if t.get("description"):
            row[YK["description"]] = t["description"]
        for c, text in zip(YK["befriend"], befriend):
            row[c] = text
        cp = row[YK["catchphrase"]]
        row[YK["catchphrase"]] = "0" if cp in ("なし", "", "0") else (t.get("catchphrase") or cp)
        yk.rows.append(row)

        if native:
            s = list(cat.jp_sk[i])
            if t.get("skill_name"):
                s[SK["name"]] = t["skill_name"]
            if t.get("skill_description"):
                s[SK["description"]] = t["skill_description"]
            sk.rows.append(s)
            for r, text in zip(cat.jp_lv[i], levels):
                r = list(r)
                r[2] = text
                lv.rows.append(r)
        else:
            d = standins[i]
            s = list(cat.ww_sk[d])
            s[0] = i
            s[SK["name"]] = t.get("skill_name") or s[SK["name"]]
            sk.rows.append(s)
            for r in cat.ww_lv[d]:
                r = list(r)
                r[0] = i
                lv.rows.append(r)

        if f"art_{i}.png" in jp_art and f"art_{i}.png" not in have_art:
            art.rows.append(list(jp_art[f"art_{i}.png"]))
            have_art.add(f"art_{i}.png")
        lt = cat.jp_yk[i][YK["level_type"]]
        for r in jp_levels:
            if r[0] == lt and (r[0], r[1]) not in have_levels:
                lvl.rows.append(r)
                have_levels.add((r[0], r[1]))
        for r in files:
            if r[1] in failed or r[1] in have_files:
                continue
            res.rows.append([str(next_res_id), r[1], r[2], today, "1", "4.0.6", r[6] if len(r) > 6 else ""])
            have_files.add(r[1])
            next_res_id += 1
        added.append(i)

    if not added:
        sys.exit("Nothing was added.")
    for tbl in (yk, sk, lv, art, lvl, res):
        tbl.save()
    if a.gacha:
        add_to_gacha(a.resources, a.gacha, [(i, min(int(cat.jp_yk[i][YK["rank"]]), MAX_RANK)) for i in added])
    bump_versions(a.resources, {"ywp_mst_youkai", "ywp_mst_youkai_skill", "ywp_mst_youkai_skill_level",
                                "ywp_mst_youkai_view_2d", "ywp_mst_youkai_level", "ywp_mst_version_resource"})
    print(f"Added {len(added)} Yo-kai" + (f"; skipped {len(skipped)} whose bundle failed to download" if skipped else "")
          + (f"; replaced {len(replacing)} leftover untranslated Soultimates" if replacing else ""))
    print("Done. Rebuild the server: docker compose up -d --build wibwob")


def add_to_gacha(resources, gacha_id, entries):
    path = os.path.join(resources, "gacha_pool.txt")
    with open(path, encoding="utf-8-sig") as f:
        pools = json.load(f)
    pool = pools.get(str(gacha_id))
    if not pool or "youkai" not in pool:
        sys.exit(f"Crank-a-kai {gacha_id} has no Yo-kai pool; pick one listed by `gachas`.")
    buckets = sorted(int(k) for k in pool["youkai"] if k.isdigit())
    for i, rank in entries:
        b = str(min(max(rank, buckets[0]), buckets[-1]))
        if int(i) not in pool["youkai"][b]:
            pool["youkai"][b].append(int(i))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pools, f, ensure_ascii=False, indent=4)
    print(f"Added {len(entries)} Yo-kai to Crank-a-kai {gacha_id}")


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


# ---------------------------------------------------------------- listing

def cmd_list(a):
    cat = Catalog(a.jp, a.resources)
    ids = cat.eligible()
    if a.search:
        ids = [i for i in ids if a.search in cat.jp_yk[i][1]]
    if a.rank:
        ids = [i for i in ids if cat.jp_yk[i][YK["rank"]] == str(a.rank)]
    for i in ids:
        r = cat.jp_yk[i]
        how = "own" if cat.native(i) else "stand-in"
        print(f"{i}\trank {r[YK['rank']]:>2}\ttribe {r[4]}\tsoultimate {how:8}\t{r[1]}")
    native = sum(1 for i in ids if cat.native(i))
    print(f"{len(ids)} Yo-kai: {native} keep their own Soultimate, {len(ids) - native} get a stand-in", file=sys.stderr)


def cmd_gachas(a):
    with open(os.path.join(a.resources, "gacha_pool.txt"), encoding="utf-8-sig") as f:
        pools = json.load(f)
    for gid, p in pools.items():
        if "youkai" in p:
            print(f"{gid}\tbuckets " + ", ".join(f"{k}:{len(v)}" for k, v in p["youkai"].items()))


# ---------------------------------------------------------------- CLI

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch")
    f.add_argument("--jp", required=True)
    f.add_argument("--app-version")

    lst = sub.add_parser("list")
    lst.add_argument("--jp", required=True)
    lst.add_argument("--resources", required=True)
    lst.add_argument("--search")
    lst.add_argument("--rank", type=int)

    g = sub.add_parser("gachas")
    g.add_argument("--resources", required=True)

    for name in ("translate", "import"):
        s = sub.add_parser(name)
        s.add_argument("--jp", required=True)
        s.add_argument("--resources", required=True)
        s.add_argument("--translations", required=True)
        who = s.add_mutually_exclusive_group(required=True)
        who.add_argument("--ids", nargs="+")
        who.add_argument("--all", action="store_true")
        s.add_argument("--native-only", action="store_true", help="only Yo-kai whose own Soultimate works")
        s.add_argument("--limit", type=int)
        if name == "translate":
            s.add_argument("--engine", choices=["claude-code", "api"], default="claude-code")
            s.add_argument("--model", default="haiku", help="model for the engine (default: haiku)")
            s.add_argument("--batch", type=int, default=10)
        else:
            s.add_argument("--data", required=True)
            s.add_argument("--gacha", type=int, help="also add them to this Crank-a-kai pool (see `gachas`)")
            s.add_argument("--apply", action="store_true")
            s.add_argument("--allow-japanese", action="store_true")
            s.add_argument("--skip-download", action="store_true", help=argparse.SUPPRESS)
            s.add_argument("--workers", type=int, default=8)
            s.add_argument("--show", type=int, default=15)
    a = p.parse_args()
    if a.cmd == "translate" and a.engine == "api" and a.model == "haiku":
        a.model = "claude-haiku-5-5"
    {"fetch": cmd_fetch, "list": cmd_list, "gachas": cmd_gachas, "translate": cmd_translate,
     "import": cmd_import}[a.cmd](a)


if __name__ == "__main__":
    main()
