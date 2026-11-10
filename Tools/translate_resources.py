"""English text for the Japanese master tables in Resources/.

Works on strings, not tables: every cell that contains Japanese is collected
into one dictionary (Japanese text -> English text), and applying it rewrites
each cell that has an entry. Numbers, ids, stats and ranks are never touched.

  scan    Collect the Japanese strings and fill in official English where the
          Wibble Wobble tables have the identical row. Prints how much is left.
              python3 Tools/translate_resources.py scan --resources Resources \\
                  --official ../wibwob.old/WWR_BACKUP/Resources

  apply   Write the English into Resources/. The untouched Japanese files are
          kept in Resources.jp/ the first time, and apply always starts from them.
              python3 Tools/translate_resources.py apply --resources Resources

Official English is only taken from a Wibble Wobble row whose every non-text
cell (ids, rank, stats, skill numbers) equals the Japanese row, so text for
anything that was changed or re-balanced since is not reused. The one exception
is Yo-kai and item names, matched by id alone, since a name does not change
when stats do.

The dictionary lives in translations/strings.json next to Resources/.
"""
import argparse
import collections
import json
import os
import re
import shutil
import sys

JP = re.compile(r"[぀-ヿ㐀-䶿一-鿿ｦ-ﾟ]")
# Tables where a name can be matched by id alone: file -> column of the name
NAME_COLUMNS = {"ywp_mst_youkai": 1, "ywp_mst_item": 2}


def has_jp(text):
    return isinstance(text, str) and JP.search(text) is not None


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def table_rows(doc):
    """Rows of an NHN table ({"tableData": "a|b*c|d"}), or None for any other shape."""
    if isinstance(doc, dict) and isinstance(doc.get("tableData"), str):
        return [row.split("|") for row in doc["tableData"].split("*")]
    return None


def walk_strings(node, visit):
    """Calls visit(text) for every string in a JSON document and replaces it with the result."""
    if isinstance(node, dict):
        return {k: walk_strings(v, visit) for k, v in node.items()}
    if isinstance(node, list):
        return [walk_strings(v, visit) for v in node]
    if isinstance(node, str):
        return visit(node)
    return node


def master_files(resources):
    return sorted(f[:-4] for f in os.listdir(resources) if f.startswith("ywp_mst_") and f.endswith(".txt"))


def store_path(resources):
    return os.path.join(os.path.dirname(os.path.abspath(resources)), "translations", "strings.json")


def read_store(resources):
    return load(store_path(resources)) or {}


def write_store(resources, store):
    path = store_path(resources)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=0, sort_keys=True)


def official_pairs(jp_rows, en_rows, name_column):
    """Yields (japanese, english, how) for cells whose row is identical apart from its text."""
    by_id = collections.defaultdict(list)
    for row in en_rows:
        by_id[row[0]].append(row)
    for row in jp_rows:
        candidates = by_id.get(row[0], [])
        text_cols = [i for i, cell in enumerate(row) if has_jp(cell)]
        if not text_cols or not candidates:
            continue
        exact = None
        for en in candidates:
            width = min(len(row), len(en))
            fixed = [i for i in range(width) if i not in text_cols]
            if len(fixed) >= 3 and all(row[i] == en[i] for i in fixed):
                exact = en
                break
        if exact is not None:
            for i in text_cols:
                if i < len(exact) and exact[i] and not has_jp(exact[i]):
                    yield row[i], exact[i], "official"
        elif name_column is not None and name_column in text_cols and len(candidates) == 1:
            en = candidates[0]
            if name_column < len(en) and en[name_column] and not has_jp(en[name_column]):
                yield row[name_column], en[name_column], "official-name"


def scan(args):
    source = os.path.join(os.path.dirname(os.path.abspath(args.resources)), "Resources.jp")
    read_from = source if os.path.isdir(source) else args.resources
    borrowed = set()
    borrowed_list = os.path.join(os.path.dirname(os.path.abspath(args.resources)), "Resources.from-wibwob.list")
    if os.path.exists(borrowed_list):
        with open(borrowed_list, encoding="utf-8") as f:
            borrowed = {line.strip()[:-4] for line in f if line.strip().endswith(".txt")}

    store = read_store(args.resources)
    per_table = []
    seen = set()
    for name in master_files(read_from):
        if name in borrowed:
            continue  # already English: it came from Wibble Wobble
        doc = load(os.path.join(read_from, name + ".txt"))
        if doc is None:
            continue
        strings = []
        rows = table_rows(doc)
        if rows is not None:
            strings = [cell for row in rows for cell in row if has_jp(cell)]
        else:
            walk_strings(doc, lambda text: strings.append(text) or text if has_jp(text) else text)
        if not strings:
            continue
        for text in strings:
            store.setdefault(text, {"en": "", "source": ""})
        seen.update(strings)

        found = 0
        if args.official and rows is not None:
            en_rows = table_rows(load(os.path.join(args.official, name + ".txt")))
            if en_rows:
                for jp, en, how in official_pairs(rows, en_rows, NAME_COLUMNS.get(name)):
                    entry = store[jp]
                    if not entry["en"] or (entry["source"] == "official-name" and how == "official"):
                        entry["en"], entry["source"] = en, how
                        found += 1
        per_table.append((name, len(strings), len(set(strings)), sum(len(s) for s in set(strings)), found))

    write_store(args.resources, store)
    print(f"{'table':<44}{'cells':>8}{'unique':>8}{'chars':>9}{'official':>9}")
    for name, cells, unique, chars, found in sorted(per_table, key=lambda t: -t[3]):
        print(f"{name:<44}{cells:>8}{unique:>8}{chars:>9}{found:>9}")
    live = {k: v for k, v in store.items() if k in seen}
    done = {k: v for k, v in live.items() if v["en"]}
    todo = [k for k in live if not live[k]["en"]]
    by_source = collections.Counter(v["source"] for v in done.values())
    print(f"\nunique Japanese strings: {len(live)} ({sum(len(k) for k in live)} characters)")
    print(f"already English: {len(done)} {dict(by_source)}")
    print(f"still to translate: {len(todo)} strings, {sum(len(k) for k in todo)} characters")
    print(f"dictionary: {store_path(args.resources)}")
    return 0


def apply(args):
    root = os.path.dirname(os.path.abspath(args.resources))
    backup = os.path.join(root, "Resources.jp")
    if not os.path.isdir(backup):
        os.makedirs(backup)
        for name in master_files(args.resources):
            shutil.copy2(os.path.join(args.resources, name + ".txt"), backup)
        print(f"kept the Japanese originals in {backup}")
    store = {jp: v["en"] for jp, v in read_store(args.resources).items() if v.get("en")}
    changed_cells, files = 0, 0
    for name in master_files(backup):
        doc = load(os.path.join(backup, name + ".txt"))
        if doc is None:
            continue
        count = [0]

        def swap(text):
            if text in store:
                count[0] += 1
                return store[text]
            return text

        rows = table_rows(doc)
        if rows is not None:
            # "|" and "*" would break the table, so an entry containing either is skipped
            safe = lambda t: swap(t) if t in store and "|" not in store[t] and "*" not in store[t] else t
            doc["tableData"] = "*".join("|".join(safe(cell) for cell in row) for row in rows)
        else:
            doc = walk_strings(doc, swap)
        if count[0]:
            with open(os.path.join(args.resources, name + ".txt"), "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
            changed_cells += count[0]
            files += 1
    print(f"wrote English into {changed_cells} cells across {files} files. Rebuild the server image to use them.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--resources", default="Resources")
    s.add_argument("--official", help="folder with the Wibble Wobble (English) tables")
    a = sub.add_parser("apply")
    a.add_argument("--resources", default="Resources")
    args = ap.parse_args()
    return scan(args) if args.command == "scan" else apply(args)


if __name__ == "__main__":
    sys.exit(main())
