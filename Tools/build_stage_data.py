"""Add the stages that have no entry in Resources/stage_data.txt.

stage_data.txt tells the server which enemies appear in each stage. It was
written by hand and only covers part of the game, so a stage without an entry
cannot be started. This fills the gaps from the master tables: column 12 of
ywp_mst_stage names an enemy set, and ywp_mst_youkai_enemy_set lists the enemies
in that set.

By default existing entries are not changed. Generated ones have no first-clear
reward, no tutorial changes, and enemies are befriended by normal chance.
--refresh-enemies also brings the enemy lists of existing entries in line with
the tables, keeping their rewards, tutorial data and guaranteed befriends.

    python3 Tools/build_stage_data.py --resources Resources --dry-run
    python3 Tools/build_stage_data.py --resources Resources --capture ~/puni.flows --dry-run
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
    ap.add_argument("--capture", help="a capture file: checks the rule against the stages played in it")
    ap.add_argument("--refresh-enemies", action="store_true",
                    help="also correct the enemy lists of existing entries from the tables")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    stage_rows = [row for row in table(args.resources, "ywp_mst_stage") if row[0].isdigit() and len(row) > 12]
    enemy_ids = {row[0] for row in table(args.resources, "ywp_mst_youkai_enemy_param")}
    sets = collections.defaultdict(list)
    extra = collections.Counter()
    for row in table(args.resources, "ywp_mst_youkai_enemy_set"):
        if len(row) > 1 and row[1].isdigit():
            sets[row[0]].append(int(row[1]))
            extra[tuple(row[2:4])] += 1

    def enemies_of(row):
        # Enemies without stats cannot be put on the field, so they are left out
        return [e for e in sets.get(row[12], []) if str(e) in enemy_ids]

    path = os.path.join(args.resources, "stage_data.txt")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    by_id = {row[0]: row for row in stage_rows}
    same = differ = 0
    examples = []
    for stage, entry in data.items():
        if stage not in by_id:
            continue
        have = [e.get("id") for e in (entry or {}).get("enemy") or []]
        want = enemies_of(by_id[stage])
        if have == want:
            same += 1
        else:
            differ += 1
            if len(examples) < 5:
                examples.append((stage, have, want))

    print(f"stages in the master table: {len(stage_rows)}; enemy sets: {len(sets)}")
    print(f"other columns of the enemy set table, by how often each pair occurs: {extra.most_common(6)}")
    print(f"existing entries that list exactly the table's enemies: {same}; that differ: {differ}")
    for stage, have, want in examples:
        print(f"   {stage}: file has {have}, tables say {want}")

    if args.capture:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from captures_to_resources import flow_responses, read_request, read_response
        played = {}
        for label, body, request_body in flow_responses(args.capture):
            if label.split(" #")[0] != "gameStart":
                continue
            doc, _ = read_response(None, body)
            request = read_request(request_body) or {}
            if isinstance(doc, dict) and request.get("stageId") is not None:
                played[str(request["stageId"])] = [e.get("enemyId") for e in doc.get("enemyYoukaiList") or []]
        right = [s for s, real in played.items() if s in by_id and enemies_of(by_id[s]) == real]
        subset = [s for s, real in played.items() if s in by_id and set(real) <= set(enemies_of(by_id[s]))]
        print(f"against the real game: the tables give exactly the real enemies for {len(right)} of {len(played)} "
              f"played stages, and contain them all for {len(subset)}")
        for s, real in sorted(played.items()):
            if s not in right:
                want = enemies_of(by_id[s]) if s in by_id else "stage not in table"
                print(f"   {s}: real {real}, tables say {want}")

    added, refreshed, no_enemies = [], [], []
    sizes = collections.Counter()
    for row in stage_rows:
        stage = row[0]
        enemies = enemies_of(row)
        if stage in data:
            entry = data[stage] or {}
            have = [e.get("id") for e in entry.get("enemy") or []]
            if args.refresh_enemies and enemies and have != enemies:
                flags = {e.get("id"): e.get("defBefriends", 0) for e in entry.get("enemy") or []}
                entry["enemy"] = [{"id": e, "defBefriends": flags.get(e, 0)} for e in enemies]
                data[stage] = entry
                refreshed.append(stage)
            continue
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

    covered = sum(1 for row in stage_rows if row[0] in data)
    print(f"entries generated: {len(added)}; enemies per stage: {dict(sorted(sizes.items()))}")
    print(f"first few generated: {added[:6]}")
    if args.refresh_enemies:
        print(f"existing entries whose enemy list was corrected: {len(refreshed)} {refreshed[:8]}")
    print(f"stages whose enemy set is empty or unknown (left without an entry): {len(no_enemies)} {no_enemies[:10]}")
    print(f"stages that can be started after this: {covered} of {len(stage_rows)}")
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    if added or refreshed:
        shutil.copyfile(path, path + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        print(f"wrote {path}; previous file saved as stage_data.txt.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main())
