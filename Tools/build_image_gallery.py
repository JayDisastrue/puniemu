"""Build a browsable gallery of the downloaded images that probably contain text.

Sorts the PNG files under dataDownload/eal/ into groups by the type code in
their file name (buttons, text labels, titles, Soultimate banners, ...) and
writes plain HTML pages into dataDownload/eal/_gallery/. The server already
serves that folder, so the gallery opens in a browser at

    <your server address>/eal/_gallery/index.html

Nothing is changed or uploaded; the pages only link to the files in place.
It also writes _gallery/candidates.json, the list later translation steps use.

    python3 Tools/build_image_gallery.py
"""
import argparse
import collections
import html
import json
import os
import re
import sys

# group -> (label, file-name tokens that put an image in it). First match wins.
GROUPS = [
    ("btn", "Buttons", {"btn", "button"}),
    ("text", "Text labels", {"text", "txt", "tx", "word", "msg", "message"}),
    ("ttl", "Titles", {"ttl", "title", "headline", "logo", "name", "caption"}),
    ("telop", "Soultimate and cut-in banners", {"telop"}),
    ("banner", "Banners and notices", {"banner", "bnr", "info", "notice", "news", "help", "tutorial", "tuto"}),
    ("tab", "Tabs, menus and windows", {"tab", "menu", "window", "win", "dialog", "popup", "label", "plate"}),
    ("image", "Event and map images", {"image", "img"}),
]
SKIP_PREFIX = ("skill", "new")   # Soultimate animation frames: tens of thousands, no text
PER_PAGE = 240
STYLE = """
body{font:14px/1.4 system-ui,sans-serif;margin:16px;background:#1b1d21;color:#e8eaed}
a{color:#8ab4f8} h1{font-size:18px} nav a{margin-right:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
figure{margin:0;padding:6px;border:1px solid #3a3d44;border-radius:6px;
 background:repeating-conic-gradient(#2a2d33 0 25%,#23262b 0 50%) 0 0/16px 16px}
img{max-width:100%;max-height:150px;display:block;margin:0 auto}
figcaption{font-size:11px;word-break:break-all;margin-top:4px;color:#aeb4bd}
"""


def tokens(name):
    return [t for t in re.split(r"[_\-.]", name.lower()) if t]


def classify(name):
    parts = tokens(name)
    if not parts or parts[0].rstrip("0123456789") in SKIP_PREFIX:
        return None
    for key, _, words in GROUPS:
        if words.intersection(parts):
            return key
    return None


def page(title, nav, body):
    return (f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>{STYLE}</style>"
            f"</head><body><h1>{html.escape(title)}</h1><nav>{nav}</nav>{body}</body></html>")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--assets", default=os.path.join("dataDownload", "eal"))
    args = ap.parse_args()
    if not os.path.isdir(args.assets):
        print(f"{args.assets} not found; run fetch_puni_assets.py first")
        return 1

    groups = collections.defaultdict(list)
    total = 0
    for folder, dirs, files in os.walk(args.assets):
        dirs[:] = [d for d in dirs if d != "_gallery"]
        for name in files:
            if not name.lower().endswith(".png"):
                continue
            total += 1
            key = classify(name)
            if key:
                rel = os.path.relpath(os.path.join(folder, name), args.assets).replace(os.sep, "/")
                groups[key].append(rel)

    out = os.path.join(args.assets, "_gallery")
    os.makedirs(out, exist_ok=True)
    index_rows = []
    for key, label, _ in GROUPS:
        items = sorted(groups.get(key, []), key=lambda rel: rel.rsplit("/", 1)[-1])
        pages = max(1, (len(items) + PER_PAGE - 1) // PER_PAGE)
        for n in range(pages):
            chunk = items[n * PER_PAGE:(n + 1) * PER_PAGE]
            nav = "<a href='index.html'>All groups</a>" + "".join(
                f"<a href='{key}_{i + 1}.html'>{'<b>' if i == n else ''}{i + 1}{'</b>' if i == n else ''}</a>"
                for i in range(pages))
            figures = "".join(
                f"<figure><a href='../{html.escape(rel)}'><img loading='lazy' src='../{html.escape(rel)}' alt=''></a>"
                f"<figcaption>{html.escape(rel.rsplit('/', 1)[-1])}</figcaption></figure>" for rel in chunk)
            with open(os.path.join(out, f"{key}_{n + 1}.html"), "w", encoding="utf-8") as f:
                f.write(page(f"{label} ({len(items)}) - page {n + 1} of {pages}", nav, f"<div class='grid'>{figures}</div>"))
        index_rows.append(f"<li><a href='{key}_1.html'>{html.escape(label)}</a>: {len(items)} images</li>")
        print(f"  {label:<32}{len(items):>6}")
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page("Images that probably contain text", "", f"<ul>{''.join(index_rows)}</ul>"))
    with open(os.path.join(out, "candidates.json"), "w", encoding="utf-8") as f:
        json.dump({key: sorted(v) for key, v in groups.items()}, f, ensure_ascii=False)

    picked = sum(len(v) for v in groups.values())
    print(f"{picked} of {total} PNG files look like they carry text")
    print(f"gallery written to {out}; open <server address>/eal/_gallery/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
