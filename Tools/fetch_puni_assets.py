"""Download the game's asset files (the "data download") for Puniemu to serve.

Reads the asset list in Resources/ywp_mst_version_resource.txt (or the untouched
copy in Resources.jp/) and saves every file under dataDownload/eal/, in the
layout the client asks for. The server then serves that folder at /eal.

    python3 Tools/fetch_puni_assets.py --limit 20        # small test batch first
    python3 Tools/fetch_puni_assets.py                   # everything

Safe to stop and re-run: files already downloaded are skipped. It does not ask
for anything it already has, and waits between requests.
"""
import argparse
import concurrent.futures
import json
import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request

FILESERVER = "https://resource.yw-p.com/eal"
HEADERS = {"User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; Pixel 7 Build/TQ3A.230901.001)",
           "Accept-Encoding": "identity"}


def asset_list(resources):
    """Yields (relative path, url) per asset. Row columns: 1 file name, 3 and 5 the two folder parts."""
    root = os.path.dirname(os.path.abspath(resources))
    for folder in (os.path.join(root, "Resources.jp"), resources):
        path = os.path.join(folder, "ywp_mst_version_resource.txt")
        if os.path.exists(path):
            break
    else:
        raise SystemExit("ywp_mst_version_resource.txt not found; run fetch_puni_resources.py first")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)["tableData"]
    seen = set()
    for row in data.split("*"):
        cols = row.split("|")
        if len(cols) < 6 or not cols[1]:
            continue
        rel = f"{cols[5]}/{cols[3]}/{cols[1]}"
        # Never let a row write outside the output folder
        if rel in seen or ".." in rel.split("/") or rel.startswith("/"):
            continue
        seen.add(rel)
        yield rel, f"{FILESERVER}/{rel}"


def fetch(url, dest, retries, delay):
    part = dest + ".part"
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as r, open(part, "wb") as f:
                shutil.copyfileobj(r, f)
            os.replace(part, dest)
            time.sleep(delay)
            return os.path.getsize(dest), None
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return 0, f"HTTP {e.code}"
            error = f"HTTP {e.code}"
        except (urllib.error.URLError, OSError) as e:
            error = str(e)
        time.sleep(delay + 2 * attempt)
    if os.path.exists(part):
        os.remove(part)
    return 0, error


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resources", default="Resources")
    ap.add_argument("--out", default=os.path.join("dataDownload", "eal"))
    ap.add_argument("--limit", type=int, default=0, help="download at most this many missing files")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.2, help="seconds each worker waits after a file")
    ap.add_argument("--min-free-gb", type=float, default=5, help="stop when the disk has less free space than this")
    args = ap.parse_args()

    assets = list(asset_list(args.resources))
    os.makedirs(args.out, exist_ok=True)
    missing = [(rel, url) for rel, url in assets
               if not os.path.exists(os.path.join(args.out, rel)) or os.path.getsize(os.path.join(args.out, rel)) == 0]
    free = shutil.disk_usage(args.out).free / 1e9
    print(f"assets listed: {len(assets)}; already here: {len(assets) - len(missing)}; to download: {len(missing)}")
    print(f"free disk space: {free:.1f} GB")
    if assets:
        print(f"example: {assets[0][1]}")
    if args.limit:
        missing = missing[:args.limit]
        print(f"limited to {len(missing)} files this run")
    if not missing:
        return 0

    lock = threading.Lock()
    state = {"done": 0, "bytes": 0, "failed": [], "stop": False}
    started = time.time()

    def work(item):
        rel, url = item
        if state["stop"]:
            return
        dest = os.path.join(args.out, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        size, error = fetch(url, dest, retries=4, delay=args.delay)
        with lock:
            state["done"] += 1
            state["bytes"] += size
            if error:
                state["failed"].append((rel, error))
            if state["done"] % 200 == 0 or state["done"] == len(missing):
                rate = state["bytes"] / max(time.time() - started, 1) / 1e6
                print(f"  {state['done']}/{len(missing)} files, {state['bytes'] / 1e9:.2f} GB, {rate:.1f} MB/s, "
                      f"{len(state['failed'])} failed", flush=True)
                if shutil.disk_usage(args.out).free / 1e9 < args.min_free_gb:
                    state["stop"] = True
                    print(f"stopping: less than {args.min_free_gb} GB free")

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, missing))

    print(f"\ndownloaded {state['done'] - len(state['failed'])} files, {state['bytes'] / 1e9:.2f} GB")
    if state["failed"]:
        reasons = {}
        for _, error in state["failed"]:
            reasons[error] = reasons.get(error, 0) + 1
        print(f"failed: {len(state['failed'])} {reasons}; first few: {[rel for rel, _ in state['failed'][:5]]}")
        print("run again to retry (files the server answered 403/404 for will fail again)")
    return 1 if state["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
