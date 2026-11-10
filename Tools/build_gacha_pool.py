"""Write crank pools (Resources/gacha_pool.txt) for every crank in ywp_mst_gacha.

The real pools and odds never leave NHN's servers, so they cannot be fetched.
This builds them instead: every crank without a pool gets one with Yo-kai
grouped by rank plus item tiers, using one of the odds profiles below.
Pools already in gacha_pool.txt are kept unless --replace is given.

    python3 Tools/build_gacha_pool.py --resources Resources --dry-run
    python3 Tools/build_gacha_pool.py --resources Resources
    python3 Tools/build_gacha_pool.py --resources Resources --profile all --replace
    python3 Tools/build_gacha_pool.py --resources Resources --config my_pool.json

Profiles (chance per pull):
  all      Every rank can drop. This is the default. Not published anywhere; a made-up
           curve that gets rarer with rank:
           E 30, D 22, C 16, B 11, A 7, S 4, SS 2.4, SSS 1.5, Z 1, ZZ 0.6, ZZZ 0.35,
           UZ 0.22, UZ+ 0.14, UZ++ 0.09, items 3.7 (3.6 book, 0.1 G book).
  modern   Rank totals published for a late-2026 event crank:
           Z 59.8, ZZ 23, ZZZ 8, UZ 2.7, UZ+ 2, UZ++ 0.8, items 3.7.
           Yo-kai below Z do not drop.
  classic  A fan-site estimate for the original crank: B 55, A 30, S 10, items 5.

Pity: after --pity-pulls pulls on a crank without a Yo-kai of --pity-rank or
better, the next pull is guaranteed one. Default 50 pulls, rank UZ. 0 turns it off.

A --config file is JSON in the same shape as a profile, e.g.
  {"ranks": {"9": 61.1, "13": 1.2},
   "items": [{"key": "i1", "weight": 3.6, "rank": 4, "names": ["ひっさつの秘伝書"]},
             {"key": "i2", "weight": 0.1, "rank": 7, "ids": [123456]}]}
Item tiers match items by exact name in ywp_mst_item or by id. "rank" is the
rank (and capsule colour) the prize is shown with.

Ranks: 1 E, 2 D, 3 C, 4 B, 5 A, 6 S, 7 SS, 8 SSS, 9 Z, 10 ZZ, 11 ZZZ, 12 UZ, 13 UZ+, 14 UZ++.
Rebuild the server image afterwards: Resources are compiled in.
"""
import argparse
import collections
import json
import os
import shutil
import sys

RANK_NAMES = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "S", 7: "SS", 8: "SSS", 9: "Z", 10: "ZZ", 11: "ZZZ",
              12: "UZ", 13: "UZ+", 14: "UZ++"}
BOOK = "ひっさつの秘伝書"       # Soultimate secret book
G_BOOK = "ひっさつGの秘伝書"    # the rarer G book
BOOK_TIERS = [{"key": "i1", "weight": 3.6, "rank": 4, "names": [BOOK]},
              {"key": "i2", "weight": 0.1, "rank": 7, "names": [G_BOOK]}]
PROFILES = {
    "modern": {"ranks": {9: 59.8, 10: 23.0, 11: 8.0, 12: 2.7, 13: 2.0, 14: 0.8}, "items": BOOK_TIERS},
    "classic": {"ranks": {4: 55.0, 5: 30.0, 6: 10.0},
                "items": [{"key": "i1", "weight": 4.9, "rank": 4, "names": [BOOK]},
                          {"key": "i2", "weight": 0.1, "rank": 7, "names": [G_BOOK]}]},
    "all": {"ranks": {1: 30, 2: 22, 3: 16, 4: 11, 5: 7, 6: 4, 7: 2.4, 8: 1.5, 9: 1.0, 10: 0.6, 11: 0.35, 12: 0.22,
                      13: 0.14, 14: 0.09},
            "items": BOOK_TIERS},
}


def table(resources, name):
    with open(os.path.join(resources, name + ".txt"), encoding="utf-8") as f:
        data = json.load(f)["tableData"]
    return [row.split("|") for row in data.split("*") if row]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resources", default="Resources")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="all")
    ap.add_argument("--pity-pulls", type=int, default=50, help="pulls before a guaranteed high rank; 0 = no pity")
    ap.add_argument("--pity-rank", type=int, default=12, help="lowest rank the pity pull gives (12 = UZ)")
    ap.add_argument("--config", help="JSON file with ranks and item tiers; overrides --profile")
    ap.add_argument("--replace", action="store_true", help="rebuild pools that already exist too")
    ap.add_argument("--dry-run", action="store_true", help="print the summary, write nothing")
    args = ap.parse_args()

    profile = PROFILES[args.profile]
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            profile = json.load(f)
    odds = {int(k): float(v) for k, v in profile.get("ranks", {}).items()}

    by_rank = collections.defaultdict(list)
    other_ranks = collections.Counter()
    for row in table(args.resources, "ywp_mst_youkai"):
        # column 0 is the Yo-kai id, column 3 its rank
        if len(row) > 3 and row[0].isdigit() and row[3].isdigit() and int(row[3]) in RANK_NAMES:
            by_rank[int(row[3])].append(int(row[0]))
        else:
            other_ranks[row[3] if len(row) > 3 else "?"] += 1
    ranks = sorted(r for r in by_rank if odds.get(r, 0) > 0)
    if not ranks:
        print("No Yo-kai found for the ranks in this profile; nothing written.")
        return 1

    # column 0 is the item id, column 2 its name
    items = [(int(row[0]), row[2]) for row in table(args.resources, "ywp_mst_item")
             if len(row) > 2 and row[0].isdigit()]
    tiers = []
    for tier in profile.get("items", []):
        names = set(tier.get("names", []))
        ids = [i for i, name in items if name in names] + [int(i) for i in tier.get("ids", [])]
        if ids and float(tier.get("weight", 0)) > 0:
            tiers.append((tier["key"], float(tier["weight"]), tier.get("rank"), sorted(set(ids))))
        else:
            print(f"WARNING: item tier {tier.get('key')} matched no item ({', '.join(names) or 'no names'}); left out.")
    for key, _, _, _ in tiers:
        if not key.startswith("i"):
            print(f"Item tier key {key!r} must start with 'i'.")
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
    known = sorted(int(k) for k in template if k.isdigit())
    if known:
        for r in RANK_NAMES:
            src = max((k for k in known if k <= r), default=known[0])
            convert[str(r)] = template[str(src)]

    weights = {str(r): odds[r] for r in ranks}
    weights.update({key: weight for key, weight, _, _ in tiers})
    entry = {
        "convertItem": convert,
        "weights": weights,
        "youkai": {str(r): by_rank[r] for r in ranks},
        "items": {key: ids for key, _, _, ids in tiers},
        "itemRanks": {key: rank for key, _, rank, _ in tiers if rank},
        "rateUp": None,
    }
    pity_ranks = [r for r in ranks if r >= args.pity_rank]
    if args.pity_pulls > 0 and pity_ranks:
        entry["pity"] = {"pulls": args.pity_pulls, "minRank": args.pity_rank}

    gacha_ids = [int(row[0]) for row in table(args.resources, "ywp_mst_gacha") if row and row[0].isdigit()]
    made, kept = 0, 0
    out = {} if args.replace else dict(existing)
    for gid in gacha_ids:
        if not args.replace and str(gid) in existing:
            kept += 1
            continue
        out[str(gid)] = dict(entry, gachaId=gid)
        made += 1

    total = sum(weights.values())
    print(f"profile: {args.config or args.profile}")
    for r in ranks:
        print(f"  rank {RANK_NAMES[r]:<4} {len(by_rank[r]):>5} Yo-kai  {100 * odds[r] / total:6.2f}% of pulls")
    for key, weight, rank, ids in tiers:
        names = [name for i, name in items if i in ids][:3]
        shown = RANK_NAMES.get(rank, "B")
        print(f"  item {key:<4} {len(ids):>5} items   {100 * weight / total:6.2f}% of pulls  shown as rank {shown}  {names}")
    if "pity" in entry:
        chance = sum(odds[r] for r in pity_ranks) / total
        print(f"pity: guaranteed {RANK_NAMES[args.pity_rank]} or better by pull {args.pity_pulls} "
              f"({100 * chance:.2f}% per pull otherwise)")
    else:
        print("pity: off")
    unused = {RANK_NAMES[r]: len(v) for r, v in sorted(by_rank.items()) if r not in ranks}
    if unused:
        print(f"ranks in the data that this profile never drops: {unused}")
    if other_ranks:
        print(f"Yo-kai rows with a rank value this server has no name for: {dict(other_ranks)}")
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
