"""Write crank pools (Resources/gacha_pool.txt) for every crank in ywp_mst_gacha.

The real pools and odds never leave NHN's servers, so they cannot be fetched.
This builds them instead: every crank without a pool gets one containing every
Yo-kai in ywp_mst_youkai, grouped by rank, with the odds per rank below.
Pools already in gacha_pool.txt are kept unless --replace is given.

    python3 Tools/build_gacha_pool.py --resources Resources
    python3 Tools/build_gacha_pool.py --resources Resources --odds my_odds.json

An odds file is JSON mapping rank number to weight, e.g. {"1": 30, "13": 0.5}.
Ranks: 1 E, 2 D, 3 C, 4 B, 5 A, 6 S, 7 SS, 8 SSS, 9 Z, 10 ZZ, 11 ZZZ, 12 UZ, 13 UZ+.
Rebuild the server image afterwards: Resources are compiled in.
"""
import argparse
import collections
import json
import os
import shutil
import sys

RANK_NAMES = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "S", 7: "SS", 8: "SSS", 9: "Z", 10: "ZZ", 11: "ZZZ",
              12: "UZ", 13: "UZ+"}
# Relative chance of each rank per pull. Only ranks that have Yo-kai are used.
DEFAULT_ODDS = {1: 28, 2: 24, 3: 18, 4: 12, 5: 8, 6: 4.5, 7: 2.5, 8: 1.2, 9: 0.7, 10: 0.45, 11: 0.3, 12: 0.2,
                13: 0.15}


def table(resources, name):
    with open(os.path.join(resources, name + ".txt"), encoding="utf-8") as f:
        data = json.load(f)["tableData"]
    return [row.split("|") for row in data.split("*") if row]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resources", default="Resources")
    ap.add_argument("--odds", help="JSON file: rank number -> weight")
    ap.add_argument("--replace", action="store_true", help="rebuild pools that already exist too")
    ap.add_argument("--dry-run", action="store_true", help="print the summary, write nothing")
    args = ap.parse_args()

    odds = dict(DEFAULT_ODDS)
    if args.odds:
        with open(args.odds, encoding="utf-8") as f:
            odds = {int(k): float(v) for k, v in json.load(f).items()}

    by_rank = collections.defaultdict(list)
    skipped = 0
    for row in table(args.resources, "ywp_mst_youkai"):
        # column 0 is the Yo-kai id, column 3 its rank
        if len(row) > 3 and row[0].isdigit() and row[3].isdigit() and int(row[3]) in RANK_NAMES:
            by_rank[int(row[3])].append(int(row[0]))
        else:
            skipped += 1
    ranks = sorted(r for r in by_rank if odds.get(r, 0) > 0)
    if not ranks:
        print("No Yo-kai with a known rank found in ywp_mst_youkai; nothing written.")
        return 1

    pool_path = os.path.join(args.resources, "gacha_pool.txt")
    existing = {}
    if os.path.exists(pool_path):
        with open(pool_path, encoding="utf-8") as f:
            existing = json.load(f)

    # What a duplicate of a maxed Yo-kai turns into, per rank. Taken from a pool that already
    # defines it; ranks it does not cover reuse the highest rank it does.
    template = {}
    for pool in existing.values():
        if isinstance(pool, dict) and pool.get("convertItem"):
            template = pool["convertItem"]
            break
    convert = {}
    if template:
        known = sorted(int(k) for k in template if k.isdigit())
        for r in RANK_NAMES:
            src = max((k for k in known if k <= r), default=known[0])
            convert[str(r)] = template[str(src)]

    gacha_ids = [int(row[0]) for row in table(args.resources, "ywp_mst_gacha") if row and row[0].isdigit()]
    total = sum(odds[r] for r in ranks)
    made, kept = 0, 0
    out = {} if args.replace else dict(existing)
    for gid in gacha_ids:
        if not args.replace and str(gid) in existing:
            kept += 1
            continue
        out[str(gid)] = {
            "gachaId": gid,
            "convertItem": convert,
            "weights": {str(r): odds[r] for r in ranks},
            "youkai": {str(r): by_rank[r] for r in ranks},
            "items": {},
            "rateUp": None,
        }
        made += 1

    print(f"Yo-kai read: {sum(len(v) for v in by_rank.values())} ({skipped} rows skipped: no usable rank)")
    for r in ranks:
        print(f"  rank {RANK_NAMES[r]:<4} {len(by_rank[r]):>5} Yo-kai  {100 * odds[r] / total:6.2f}% of pulls")
    print(f"cranks in ywp_mst_gacha: {len(gacha_ids)}; pools built: {made}; existing pools kept: {kept}")
    if not convert:
        print("WARNING: no existing pool defines convertItem, so pulling a maxed Yo-kai will fail.")
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    if os.path.exists(pool_path):
        shutil.copyfile(pool_path, pool_path + ".bak")
    with open(pool_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wrote {pool_path} ({len(out)} pools); previous file saved as gacha_pool.txt.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
