"""Print facts from a capture that help line the emulator up with the real game.

Shows only request names, stage ids, enemy ids and master-table rows. No account
data, tokens or save contents are printed.

    python3 Tools/inspect_capture.py ~/puni.flows --resources Resources
"""
import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from captures_to_resources import flow_responses, read_request, read_response  # noqa: E402


def rows(resources, name):
    root = os.path.dirname(os.path.abspath(resources))
    for folder in (os.path.join(root, "Resources.jp"), resources):
        path = os.path.join(folder, name + ".txt")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
            if isinstance(doc, dict) and isinstance(doc.get("tableData"), str):
                return [r.split("|") for r in doc["tableData"].split("*") if r]
            return doc
    return []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("--resources", default="Resources")
    args = ap.parse_args()

    names = collections.Counter()
    holders = collections.defaultdict(set)
    stages = {}
    for label, body, request_body in flow_responses(args.capture):
        name = label.split(" #")[0]
        doc, _ = read_response(None, body)
        if not isinstance(doc, dict):
            continue
        names[name] += 1
        for key in ("ywp_mst_daily_event_mission", "mstMapMobPeriodNoList", "ywp_mst_map_mob"):
            if key in doc:
                holders[key].add(f"{name}({'empty' if doc[key] in ('', [], {}, None) else 'has data'})")
        if name == "gameStart":
            request = read_request(request_body) or {}
            enemies = [e.get("enemyId") for e in doc.get("enemyYoukaiList") or [] if isinstance(e, dict)]
            if request.get("stageId") is not None:
                stages[str(request["stageId"])] = enemies

    print(f"request types captured ({len(names)}):")
    print("  " + " ".join(f"{n}x{c}" for n, c in sorted(names.items())))
    for key in ("ywp_mst_daily_event_mission", "mstMapMobPeriodNoList", "ywp_mst_map_mob"):
        print(f"{key}: sent in {sorted(holders[key]) or 'no captured response'}")

    stage_data = rows(args.resources, "stage_data") or {}
    enemy_param = {r[0]: r for r in rows(args.resources, "ywp_mst_youkai_enemy_param")}
    enemy_set = rows(args.resources, "ywp_mst_youkai_enemy_set")
    stage_rows = {r[0]: r for r in rows(args.resources, "ywp_mst_stage")}
    print(f"\nstages played in the capture: {len(stages)}")
    agree = 0
    for stage, enemies in sorted(stages.items()):
        have = [e.get("id") for e in (stage_data.get(stage) or {}).get("enemy") or []]
        mark = "same as stage_data" if have == enemies else f"stage_data has {have or 'no entry'}"
        agree += have == enemies
        prefix = all(str(e)[:-2] == stage for e in enemies)
        print(f"  stage {stage}: real enemies {enemies} | id-prefix rule {'holds' if prefix else 'BREAKS'} | {mark}")
    print(f"stage_data matches the real game for {agree} of {len(stages)} played stages")

    print("\nenemy table: columns", len(next(iter(enemy_param.values()), [])), "| rows", len(enemy_param))
    for stage, enemies in list(sorted(stages.items()))[:4]:
        for e in enemies[:2]:
            print(f"  enemy_param[{e}] = {enemy_param.get(str(e))}")
    if isinstance(enemy_set, list) and enemy_set:
        print("enemy_set: columns", len(enemy_set[0]), "| rows", len(enemy_set))
        wanted = {str(e) for es in stages.values() for e in es} | set(stages)
        shown = 0
        for r in enemy_set:
            if wanted.intersection(r) and shown < 12:
                print("  enemy_set row:", r)
                shown += 1
        if not shown:
            print("  first rows:", enemy_set[:4])
    for stage in list(sorted(stages))[:4]:
        print(f"  ywp_mst_stage[{stage}] = {stage_rows.get(stage)}")
    # hand-written entries that do not follow the id-prefix rule
    odd = [(s, [e.get('id') for e in (v or {}).get('enemy') or []]) for s, v in stage_data.items()
           if any(str(e.get('id'))[:-2] != s for e in (v or {}).get('enemy') or [])]
    print(f"\nstage_data entries whose enemies are not numbered after the stage: {len(odd)}; examples:")
    for s, es in odd[:8]:
        print(f"  {s}: {es}  stage row: {(stage_rows.get(s) or [])[:10]}")
    missing = [s for s in stage_rows if s not in stage_data]
    print(f"stages with no layout: {len(missing)}; examples with their rows:")
    for s in missing[:6]:
        print(f"  {s}: {stage_rows[s][:14]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
