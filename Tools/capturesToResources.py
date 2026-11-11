"""
capturesToResources.py

Turns captured getMaster.nhn responses into embedded-resource table files
(Resources/<tableName>.txt), the format GameDataManager.cs loads.

Input can be either:
  * raw response bodies as captured off the wire (encrypted, base64url) -- the
    script decrypts them with the project's existing NHN helper, or
  * already-decrypted getMaster JSON dumps ({ "<table>": { "tableData": ... }, ... }).

It auto-detects which, per file. Point it at a directory of captures (e.g. a
mitmproxy export) and an output directory.

Usage:
    python3 capturesToResources.py <captures_dir> <output_resources_dir>

Nothing here contacts any server. It only reads local files you captured by
your own means and reshapes them into the files the emulator embeds.
"""

import json
import os
import sys


def load_getmaster_dict(raw: str) -> dict:
    """Return the decrypted getMaster table dict from one captured body.

    Tries to treat `raw` as already-decrypted JSON first; if that fails,
    decrypts it with the project's NHN scheme and parses the result.
    """
    text = raw.strip()
    if not text:
        raise ValueError("empty body")

    # Case 1: already decrypted JSON.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    # Case 2: encrypted body straight off the wire. Only now do we need the
    # project's crypto helper (and its Cryptodome dependency).
    from sharedLogic import NHN
    decrypted = NHN.decrypt_res(text)
    obj = json.loads(decrypted)
    if not isinstance(obj, dict):
        raise ValueError("decrypted body is not a JSON object")
    return obj


def is_table_object(value) -> bool:
    """A table entry is a JSON object carrying a tableData field."""
    return isinstance(value, dict) and "tableData" in value


def extract_tables(getmaster: dict) -> dict:
    """Pull { tableName: table_object } pairs out of a getMaster dict.

    getMaster responses key tables by name at the top level. Non-table
    metadata keys (status codes, tokens, etc.) are skipped.
    """
    return {name: obj for name, obj in getmaster.items() if is_table_object(obj)}


def main(captures_dir: str, out_dir: str) -> int:
    if not os.path.isdir(captures_dir):
        print(f"captures dir not found: {captures_dir}", file=sys.stderr)
        return 2

    os.makedirs(out_dir, exist_ok=True)

    written = {}   # tableName -> source file (for collision reporting)
    skipped_files = []

    for entry in sorted(os.listdir(captures_dir)):
        path = os.path.join(captures_dir, entry)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read()
            getmaster = load_getmaster_dict(raw)
        except Exception as e:  # noqa: BLE001 - report and move on
            skipped_files.append((entry, str(e)))
            continue

        tables = extract_tables(getmaster)
        if not tables:
            skipped_files.append((entry, "no table objects found"))
            continue

        for name, obj in tables.items():
            out_path = os.path.join(out_dir, f"{name}.txt")
            # Serialize the single-table object exactly as the emulator expects:
            # a JSON object with a tableData field. Compact, UTF-8, no BOM.
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
            if name in written and written[name] != entry:
                print(f"  note: {name} overwritten from {entry} "
                      f"(was {written[name]})")
            written[name] = entry

    print(f"\nWrote {len(written)} table(s) to {out_dir}")
    for name in sorted(written):
        print(f"  {name}.txt")

    if skipped_files:
        print(f"\nSkipped {len(skipped_files)} file(s):")
        for entry, why in skipped_files:
            print(f"  {entry}: {why}")

    return 0 if written else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
