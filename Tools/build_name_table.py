"""Fill in English Yo-kai names from the English Yo-kai Watch wiki.

The wiki keeps Medallium lists for this game, one page per tribe, giving each
Yo-kai's Medallium number and English name. The master table has the same
number (column 14 of ywp_mst_youkai), so the two join without guessing.

Names go into translations/strings.json (the dictionary translate_resources.py
applies), in this order of trust:
  1. official   already there, from an identical Wibble Wobble row - kept
  2. wiki       the wiki's name for that Medallium number
  3. romaji     no wiki entry: the Japanese reading (column 31) in Hepburn romaji

    python3 Tools/build_name_table.py --resources Resources            # report only
    python3 Tools/build_name_table.py --resources Resources --write    # save the names

Run translate_resources.py scan first so the dictionary exists.
"""
import argparse
import collections
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://yokaiwatch.fandom.com/api.php"
LIST_PAGE = "List of Yo-kai by Medallium Number (Yo-kai Watch: Wibble Wobble)"
TRIBE_PAGES = ["", "/Brave", "/Mysterious", "/Tough", "/Charming", "/Heartful", "/Shady", "/Eerie", "/Slippery",
               "/Enma"]
ROW = re.compile(r"\{\{List/wibblewobble\|\s*(\d+)\s*\|\s*\[\[File:[^\]]*\]\]\s*\|\s*\[\[([^\]]+)\]\]")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; name-table-builder)"}

KANA = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o", "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so", "た": "ta", "ち": "chi", "つ": "tsu", "て": "te",
    "と": "to", "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no", "は": "ha", "ひ": "hi", "ふ": "fu",
    "へ": "he", "ほ": "ho", "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo", "や": "ya", "ゆ": "yu",
    "よ": "yo", "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro", "わ": "wa", "を": "o", "ん": "n",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go", "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze",
    "ぞ": "zo", "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do", "ば": "ba", "び": "bi", "ぶ": "bu",
    "べ": "be", "ぼ": "bo", "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po", "ゔ": "vu",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
}
YOON = {"ゃ": "ya", "ゅ": "yu", "ょ": "yo"}
SMALL_VOWEL = {"ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o"}


def to_hiragana(text):
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)


def romaji(reading):
    """Hepburn romaji for a kana reading. Returns '' if the text is not plain kana."""
    text = to_hiragana(reading.strip())
    out, i = [], 0
    while i < len(text):
        c = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if c == "っ":
            follow = KANA.get(nxt, "")
            out.append("t" if follow.startswith("ch") else follow[:1])
        elif c == "ー":
            if out and out[-1] and out[-1][-1] in "aiueo":
                out.append(out[-1][-1])
        elif c in KANA:
            base = KANA[c]
            if nxt in YOON and base.endswith("i") and len(base) > 1:
                stem = base[:-1]
                out.append(stem + (YOON[nxt][1:] if stem in ("sh", "ch", "j") else YOON[nxt]))
                i += 1
            elif nxt in SMALL_VOWEL and c in "ふゔてでうとど":
                out.append({"ふ": "f", "ゔ": "v", "て": "t", "で": "d", "う": "w", "と": "t", "ど": "d"}[c]
                           + SMALL_VOWEL[nxt])
                i += 1
            else:
                out.append(base)
        elif c in " 　・":
            out.append(" ")
        elif c.isascii():
            out.append(c)
        else:
            return ""
        i += 1
    words = "".join(out).split()
    return " ".join(w[:1].upper() + w[1:] for w in words)


def wiki_names(delay):
    names = {}
    for sub in TRIBE_PAGES:
        query = urllib.parse.urlencode({"action": "parse", "page": LIST_PAGE + sub, "prop": "wikitext",
                                        "format": "json"})
        req = urllib.request.Request(f"{API}?{query}", headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as r:
            text = json.load(r)["parse"]["wikitext"]["*"]
        found = ROW.findall(text)
        for number, link in found:
            # [[Page name|shown name]] -> shown name
            names[number] = link.split("|")[-1].strip()
        print(f"  wiki page {sub or '(index)':<14}{len(found):>5} names")
        time.sleep(delay)
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resources", default="Resources")
    ap.add_argument("--write", action="store_true", help="save the names into translations/strings.json")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between wiki requests")
    args = ap.parse_args()

    root = os.path.dirname(os.path.abspath(args.resources))
    source = os.path.join(root, "Resources.jp")
    table_path = os.path.join(source if os.path.isdir(source) else args.resources, "ywp_mst_youkai.txt")
    with open(table_path, encoding="utf-8") as f:
        rows = [r.split("|") for r in json.load(f)["tableData"].split("*") if r]
    store_path = os.path.join(root, "translations", "strings.json")
    if not os.path.exists(store_path):
        print("translations/strings.json not found; run translate_resources.py scan first")
        return 1
    with open(store_path, encoding="utf-8") as f:
        store = json.load(f)

    names = wiki_names(args.delay)
    print(f"wiki names: {len(names)}")

    stats = collections.Counter()
    agree = disagree = 0
    conflicts, samples, missing = [], [], []
    changes = {}
    for row in rows:
        # column 1 name, 3 rank, 7 max level, 14 Medallium number, 31 kana reading
        if len(row) < 32 or not row[3].isdigit() or int(row[3]) == 0 or not row[7].isdigit() or int(row[7]) == 0:
            continue
        jp, number, reading = row[1], row[14], row[31]
        entry = store.get(jp)
        wiki = names.get(number)
        if entry and entry.get("source", "").startswith("official") and entry.get("en"):
            stats["official (kept)"] += 1
            if wiki:
                if wiki.lower() == entry["en"].lower():
                    agree += 1
                else:
                    disagree += 1
                    conflicts.append((jp, entry["en"], wiki))
            continue
        # "Pandora (Monster Strike)" is the wiki telling two pages apart, not part of the name.
        # Kept when the Japanese name has brackets too, e.g. a (Light) variant.
        if wiki and not re.search(r"[(（]", jp):
            wiki = re.sub(r"\s*\([^)]*\)$", "", wiki) or wiki
        if wiki:
            changes[jp] = (wiki, "wiki")
            stats["wiki"] += 1
            if len(samples) < 12:
                samples.append((number, jp, wiki))
        else:
            roman = romaji(reading) or romaji(jp)
            if roman:
                changes[jp] = (roman, "romaji")
                stats["romaji"] += 1
                if len(missing) < 12:
                    missing.append((number, jp, roman))
            else:
                stats["no name found"] += 1
                if len(missing) < 12:
                    missing.append((number, jp, "(needs a reading)"))

    print(f"playable Yo-kai names: {dict(stats)}")
    print(f"check: where both exist, the wiki agrees with the official name {agree} times and differs {disagree} times")
    for jp, official, wiki in conflicts[:8]:
        print(f"   differs: {jp}  official {official!r}  wiki {wiki!r}")
    print("wiki samples:")
    for number, jp, en in samples:
        print(f"   {number:>5}  {jp}  ->  {en}")
    print("not on the wiki:")
    for number, jp, en in missing:
        print(f"   {number:>5}  {jp}  ->  {en}")

    if not args.write:
        print("report only; add --write to save these names")
        return 0
    for jp, (en, source_name) in changes.items():
        store.setdefault(jp, {})
        store[jp]["en"], store[jp]["source"] = en, source_name
    with open(store_path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=0, sort_keys=True)
    print(f"saved {len(changes)} names to {store_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
