"""
mitmproxy addon: save getMaster.nhn response bodies to files.

Records the raw (still-encrypted) response body of every getMaster.nhn call
into a captures directory, one file per response. Those files are exactly
what capturesToResources.py consumes.

Run it with mitmproxy/mitmdump against your own device's traffic:

    mitmdump -s mitm_capture_getmaster.py --listen-port 8080
    # or, to also keep a full recording:
    mitmdump -s mitm_capture_getmaster.py -w flows.mitm --listen-port 8080

Set the capture directory with the CAPTURES_DIR env var (default ./captures).
Then:

    python3 capturesToResources.py captures ../Resources

This only writes traffic your own client already received. It contacts
nothing itself.
"""

import os
from datetime import datetime

CAPTURES_DIR = os.environ.get("CAPTURES_DIR", "captures")

# Match the game's master-data endpoint. Broadened to any yw-p.com host so a
# changed path still gets recorded; capturesToResources skips bodies with no
# table objects, so over-capturing is harmless.
MATCH_HOST = "yw-p.com"
MATCH_PATH = "getMaster.nhn"

_counter = 0


def response(flow):
    global _counter
    host = flow.request.pretty_host or ""
    path = flow.request.path or ""
    if MATCH_HOST not in host or MATCH_PATH not in path:
        return

    body = flow.response.get_text(strict=False) or ""
    if not body.strip():
        return

    os.makedirs(CAPTURES_DIR, exist_ok=True)
    _counter += 1
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"getMaster_{stamp}_{_counter:04d}.txt"
    out_path = os.path.join(CAPTURES_DIR, fname)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    try:
        from mitmproxy import ctx
        ctx.log.info(f"[capture] saved {out_path} ({len(body)} bytes)")
    except Exception:  # noqa: BLE001 - logging is best-effort
        print(f"[capture] saved {out_path} ({len(body)} bytes)")
