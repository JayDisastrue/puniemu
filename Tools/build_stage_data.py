"""Add the stages that have no entry in Resources/stage_data.txt.

stage_data.txt tells the server which enemies appear in each stage. It was
written by hand and only covers part of the game, so a stage without an entry
cannot be started. This fills the gaps by rule: an enemy belongs to a stage
when its id is the stage id followed by two digits (stage 9804001 has enemies
980400101, 980400102, ...), which is how ywp_mst_youkai_enemy_param numbers them.

Existing entries are never changed. Generated ones have no first-clear reward,
no tutorial changes, and enemies are befriended by normal chance.

    python3 Tools/build_stage_data.py --resources Resources --dry-run
    python3 Tools/build_stage_data.py --resources Resources

Rebuild the server image afterwards: Resources are compiled in.
"""
import argparse
import collections
import json
import os
import shutil
import sys


def table(resources, name):
    root = os.path.dirname(os.path.abspath(resources))
    for folder in (os.path.join(root, "Resources.jp"), resources):
        path = os.path.join(folder, name + ".txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return [row.split("|") for row in json.load(f)["tableData"].split("*") if row]
    raise SystemExit(f"{name}.txt not found")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--resources", default="Resources")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    stages = [row[0] for row in table(args.resources, "ywp_mst_stage") if row[0].isdigit()]
    by_stage = collections.defaultdict(list)
    for row in table(args.resources, "ywp_mst_youkai_enemy_param"):
        enemy = row[0]
        if enemy.isdigit() and len(enemy) > 2:
            by_stage[enemy[:-2]].append(int(enemy))

    path = os.path.join(args.resources, "stage_data.txt")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # How the hand-written entries number their enemies, to show the rule holds
    follows = breaks = 0
    for stage, entry in data.items():
        for enemy in (entry or {}).get("enemy") or []:
            if str(enemy.get("id", ""))[:-2] == stage:
                follows += 1
            else:
                breaks += 1

    added, no_enemies = [], []
    sizes = collections.Counter()
    for stage in stages:
        if stage in data:
            continue
        enemies = sorted(by_stage.get(stage, []))
        if not enemies:
            no_enemies.append(stage)
            continue
        data[stage] = {
            "enemy": [{"id": enemy, "defBefriends": 0} for enemy in enemies],
            "tutorial_edit": {"requests": None, "response": None},
            "menufunc_edit": [],
            "first_reward": [],
        }
        added.append(stage)
        sizes[len(enemies)] += 1

    covered = sum(1 for stage in stages if stage in data)
    print(f"stages in the master table: {len(stages)}")
    print(f"existing entries follow the numbering rule for {follows} enemies and break it for {breaks}")
    print(f"entries generated: {len(added)}; enemies per stage: {dict(sorted(sizes.items()))}")
    print(f"first few generated: {added[:6]}")
    print(f"stages with no enemies in the enemy table (left without an entry): {len(no_enemies)} {no_enemies[:10]}")
    print(f"stages that can be started after this: {covered} of {len(stages)}")
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    if added:
        shutil.copyfile(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        print(f"wrote {path}; previous file saved as stage_data.txt.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
