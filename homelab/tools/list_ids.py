"""Write a readable list of item and Yo-kai IDs from a server's Resources folder.

Usage:
    python3 list_ids.py <Resources folder> [output.md]

For WibWob Reload the folder is WWR_BACKUP/Resources. Use the IDs with the
in-game admin commands, e.g. "<PIN> 3 25007 10" for ten Five-Star Coins.
"""
import json
import sys
from pathlib import Path

ITEM_TYPES = {
    "1": "Exporb", "2": "Food", "3": "Soultimate booster", "4": "Crank-a-kai coin",
    "5": "Evolution / fusion item", "7": "Watch part", "8": "Charm", "9": "Map warp",
    "10": "Bonus effect booster",
}


def table(folder, name):
    text = (folder / f"{name}.txt").read_text(encoding="utf-8")
    try:
        text = json.loads(text)["tableData"]
    except (ValueError, KeyError, TypeError):
        pass
    return [row.split("|") for row in text.split("*") if row]


def clean(s):
    return s.replace("\n", " ").replace("|", "/").strip()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    folder = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("ids.md")

    lines = ["# Item and Yo-kai IDs", "",
             "Admin commands: `<PIN> 3 <itemId> [count]` gives an item, `<PIN> 4 <youkaiId>` gives a Yo-kai.", ""]

    items = sorted(table(folder, "ywp_mst_item"), key=lambda r: (r[1].zfill(3), int(r[0])))
    lines += ["## Items", "", "| ID | Type | Name | Description |", "|---|---|---|---|"]
    for r in items:
        lines.append(f"| {r[0]} | {ITEM_TYPES.get(r[1], 'type ' + r[1])} | {clean(r[2])} | {clean(r[5]) if len(r) > 5 else ''} |")

    youkai = sorted(table(folder, "ywp_mst_youkai"), key=lambda r: clean(r[1]).lower())
    lines += ["", "## Yo-kai", "", "| ID | Name |", "|---|---|"]
    for r in youkai:
        lines.append(f"| {r[0]} | {clean(r[1])} |")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out}: {len(items)} items, {len(youkai)} Yo-kai")


if __name__ == "__main__":
    main()
