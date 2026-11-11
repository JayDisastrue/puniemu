"""Add the stages that have no entry in Resources/stage_data.txt.

stage_data.txt tells the server which enemies appear in each stage. It was
written by hand and only covers part of the game, so a stage without an entry
cannot be started. This fills the gaps from the master tables.

The tables do not state the stage-to-enemy link in one obvious place, so the
script tries several ways of reading it (enemy ids numbered after the stage,
and the enemy sets a stage points to), scores each against the existing
hand-written entries and, with --capture, against the stages actually played
in a capture, and uses the best-scoring one that finds enemies for a stage.

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
    ap.add_argument("--capture", help="a capture file: scores the rules against the stages played in it")
    ap.add_argument("--refresh-enemies", action="store_true",
                    help="also correct the enemy lists of existing entries (keeps rewards and befriend flags)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    stage_rows = [row for row in table(args.resources, "ywp_mst_stage") if row[0].isdigit() and len(row) > 12]
    by_id = {row[0]: row for row in stage_rows}
    enemy_ids = sorted(row[0] for row in table(args.resources, "ywp_mst_youkai_enemy_param") if row[0].isdigit())
    known = set(enemy_ids)
    by_prefix = collections.defaultdict(list)   # enemy id without its last digit(s) -> ids
    for e in enemy_ids:
        by_prefix[(e[:-2], len(e))].append(int(e))
        by_prefix[(e[:-1], len(e))].append(int(e))
    sets = collections.defaultdict(list)
    set_of_enemy = collections.defaultdict(list)
    for row in table(args.resources, "ywp_mst_youkai_enemy_set"):
        if len(row) > 1 and row[1].isdigit():
            sets[row[0]].append(int(row[1]))
            set_of_enemy[row[1]].append(row[0])

    def stage_plus_two(stage, row):       # 1001003 -> 100100301, 100100302
        return sorted(by_prefix.get((stage, len(stage) + 2), []))

    def short_stage_plus_one(stage, row):  # 30001002 -> 30001021, 30001022
        return sorted(by_prefix.get((stage[:-3] + stage[-2:], len(stage)), []))

    def named_set(stage, row):
        return [e for e in sets.get(row[12], []) if str(e) in known]

    def neighbouring_sets(stage, row):     # sets X0..X9 where the stage names X0
        base = row[12]
        found = []
        for digit in "0123456789":
            found += [e for e in sets.get(base[:-1] + digit, []) if str(e) in known and e not in found]
        return found

    rules = [("enemy id = stage id + 2 digits", stage_plus_two),
             ("enemy id = map + 2-digit stage + 1 digit", short_stage_plus_one),
             ("the enemy set the stage names", named_set),
             ("the ten enemy sets around the one the stage names", neighbouring_sets)]

    path = os.path.join(args.resources, "stage_data.txt")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    existing = {s: [e.get("id") for e in (v or {}).get("enemy") or []] for s, v in data.items() if s in by_id}

    played = {}
    if args.capture:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from captures_to_resources import flow_responses, read_request, read_response
        for label, body, request_body in flow_responses(args.capture):
            if label.split(" #")[0] != "gameStart":
                continue
            doc, _ = read_response(None, body)
            request = read_request(request_body) or {}
            if isinstance(doc, dict) and request.get("stageId") is not None and str(request["stageId"]) in by_id:
                played[str(request["stageId"])] = [e.get("enemyId") for e in doc.get("enemyYoukaiList") or []]

    print(f"stages in the master table: {len(stage_rows)}; hand-written entries: {len(existing)}; "
          f"stages played in the capture: {len(played)}")
    scored = []
    for label, rule in rules:
        real = sum(1 for s, want in played.items() if rule(s, by_id[s]) == want)
        hand = sum(1 for s, want in existing.items() if rule(s, by_id[s]) == want)
        finds = sum(1 for row in stage_rows if rule(row[0], row))
        scored.append((real, hand, label, rule))
        print(f"  rule '{label}': right for {real}/{len(played)} played, agrees with {hand}/{len(existing)} "
              f"hand-written, finds enemies for {finds}/{len(stage_rows)} stages")
    scored.sort(key=lambda t: (-t[0], -t[1]))
    order = [(label, rule) for _, _, label, rule in scored]
    print("order of preference: " + " > ".join(label for label, _ in order))

    def by_score(stage):
        for label, rule in order:
            found = rule(stage, by_id[stage])
            if found:
                return found, label
        return [], ""

    def by_pattern(stage):
        # An id pattern is trusted for a stage when its enemies include the one the
        # stage's own enemy set names; otherwise fall back to that set.
        anchor = named_set(stage, by_id[stage])
        for label, rule in rules[:2]:
            found = rule(stage, by_id[stage])
            if found and all(e in found for e in anchor):
                return found, label
        return (anchor, rules[2][0]) if anchor else by_score(stage)

    def score(method):
        return sum(1 for s, want in played.items() if method(s)[0] == want)

    print(f"picking rules by overall score: right for {score(by_score)} of {len(played)} played stages")
    print(f"picking the id pattern that fits each stage: right for {score(by_pattern)} of {len(played)} played stages")
    enemies_of = by_pattern if score(by_pattern) >= score(by_score) else by_score
    print("using: " + ("the id pattern that fits each stage" if enemies_of is by_pattern else "overall score"))

    wrong = [(s, want, enemies_of(s)[0]) for s, want in sorted(played.items()) if enemies_of(s)[0] != want]
    print(f"result: right for {len(played) - len(wrong)} of {len(played)} played stages")
    for s, want, got in wrong:
        missing = [e for e in want if e not in got]
        where = {e: (set_of_enemy.get(str(e)) or ["in no set"])[:3] for e in missing}
        print(f"   {s}: real {want}, rules give {got}; missing ones sit in sets {where}; "
              f"in enemy table: {[str(e) in known for e in missing]}; stage names set {by_id[s][12]}; "
              f"each rule alone: {[rule(s, by_id[s]) for _, rule in rules]}")

    added, refreshed, no_enemies = [], [], []
    used = collections.Counter()
    for row in stage_rows:
        stage = row[0]
        enemies, label = enemies_of(stage)
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
        used[label] += 1

    covered = sum(1 for row in stage_rows if row[0] in data)
    print(f"entries generated: {len(added)}, by rule: {dict(used)}")
    print(f"first few generated: {[(s, [e['id'] for e in data[s]['enemy']]) for s in added[:4]]}")
    if args.refresh_enemies:
        print(f"existing entries whose enemy list was corrected: {len(refreshed)} {refreshed[:8]}")
    print(f"stages no rule finds enemies for (left without an entry): {len(no_enemies)} {no_enemies[:10]}")
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
