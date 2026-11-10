"""Walk a fresh account through a Puniemu server and report which requests fail.

Stands in for the game client so the server can be checked without one. It
talks only to the server you point it at.

    python3 Tools/smoke_test.py --server http://127.0.0.1:8086 --app-ver 4.177.0

Each step prints OK, a message box the server answered with, or the HTTP error.
For an HTTP 500, the reason is in the server log (docker compose logs puni).
"""
import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

from fetch_puni_resources import HEADERS, decrypt_response, encrypt_request


class Client:
    def __init__(self, server, app_ver):
        self.server = server.rstrip("/")
        self.app_ver = app_ver
        self.udkey = ""
        self.gdkey = ""
        self.failed = []

    def get(self, path, **query):
        url = f"{self.server}{path}?{urllib.parse.urlencode(query)}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
            return json.loads(r.read().decode())

    def post(self, endpoint, **extra):
        # Handlers disagree on the spelling of the account fields, so send every spelling
        payload = {"appVer": self.app_ver, "osType": 2, "ywpToken": "0", "userId": "0", "userID": "0",
                   "deviceId": self.udkey, "deviceID": self.udkey,
                   "level5UserId": self.gdkey, "level5UserID": self.gdkey, "gdkeyValue": self.gdkey}
        payload.update(extra)
        req = urllib.request.Request(f"{self.server}/{endpoint}", data=encrypt_request(payload),
                                     headers=HEADERS, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            return decrypt_response(r.read().decode())

    def step(self, name, fn):
        try:
            res = fn()
        except urllib.error.HTTPError as e:
            print(f"FAIL  {name}: HTTP {e.code}")
            self.failed.append(name)
            return None
        except Exception as e:  # bad encryption, non-JSON body, connection refused, ...
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
            self.failed.append(name)
            return None
        msg = res.get("dialogMsg") if isinstance(res, dict) else None
        if msg:
            print(f"MSG   {name}: {msg!r}")
            self.failed.append(name)
        else:
            size = len(res) if isinstance(res, (dict, list)) else 0
            print(f"OK    {name} ({size} keys)")
        return res


RANKS = {1: "E", 2: "D", 3: "C", 4: "B", 5: "A", 6: "S", 7: "SS", 8: "SSS", 9: "Z", 10: "ZZ", 11: "ZZZ", 12: "UZ",
         13: "UZ+", 14: "UZ++"}


def tally_pulls(c, args, gacha_id):
    """Pull one crank many times and print how often each rank came out."""
    body = json.dumps({"gdkey": c.gdkey, "ymoney": 99999999}).encode()
    req = urllib.request.Request(c.server + "/admin/api/currency", data=body, method="POST",
                                 headers={"X-Admin-Password": args.admin_password, "Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except urllib.error.HTTPError as e:
        print(f"FAIL  pull tally: admin top-up answered HTTP {e.code}")
        c.failed.append("pull tally")
        return
    counts, total, order, first_high = {}, 0, [], None
    while total < args.pulls:
        try:
            res = c.post("executeGacha.nhn", gachaId=gacha_id, gachaCnt=1, activeDeckId=1, requestYoukaiId=0,
                         mstVersionVer=0, token="")
        except Exception as e:
            print(f"FAIL  pull tally after {total} pulls: {type(e).__name__}: {e}")
            c.failed.append("pull tally")
            return
        # A single prize may be written at the top level instead of in the list
        prizes = res.get("gachaPrizeList") or ([res] if res.get("prizeType") else [])
        if res.get("dialogMsg") or not prizes:
            print(f"MSG   pull tally after {total} pulls: {res.get('dialogMsg')!r}")
            c.failed.append("pull tally")
            return
        for p in prizes:
            total += 1
            is_item = p.get("prizeType") == 1
            label = ("item " if is_item else "") + RANKS.get(p.get("rarityType"), str(p.get("rarityType")))
            counts[label] = counts.get(label, 0) + 1
            if label not in order:
                order.append(label)
            if not is_item and (p.get("rarityType") or 0) >= 12 and first_high is None:
                first_high = total
    print(f"OK    pull tally: {total} pulls on crank {gacha_id}")
    for label in sorted(order, key=lambda x: (x.startswith("item"), -counts[x])):
        print(f"      {label:<10} {counts[label]:>5}  {100 * counts[label] / total:6.2f}%")
    print(f"      first UZ or better on pull: {first_high}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", required=True, help="e.g. http://127.0.0.1:8086")
    ap.add_argument("--app-ver", required=True)
    ap.add_argument("--admin-password", help="with --pulls: tops the test account up through the admin panel")
    ap.add_argument("--pulls", type=int, default=0, help="extra crank pulls to make and tally by rank")
    ap.add_argument("--stage", type=int, default=1001001, help="stage to start (default: first stage)")
    args = ap.parse_args()
    c = Client(args.server, args.app_ver)

    res = c.step("l5id active (new device)", lambda: c.get("/l5id/api/v1/active/"))
    if not res:
        return 1
    c.udkey = (res.get("udkey") or {}).get("value", "")
    res = c.step("l5id create_gdkey", lambda: c.get("/l5id/api/v1/create_gdkey/", udkey=c.udkey))
    if not res:
        return 1
    c.gdkey = (res.get("gdkey") or {}).get("value", "")
    print(f"      device {c.udkey}  account {c.gdkey}")

    c.step("init", lambda: c.post("init.nhn"))
    c.step("getMaster (all)", lambda: c.post("getMaster.nhn", tableNames="all"))
    c.step("createUser", lambda: c.post("createUser.nhn", iconID=1, playerName="SmokeTest", playerSexType="1",
                                        mstVersionVer=0))
    login = c.step("login", lambda: c.post("login.nhn"))
    if isinstance(login, dict):
        missing = [k for k, v in login.items() if v is None]
        if missing:
            print(f"      login answered null for: {' '.join(sorted(missing))}")
    # Only after createUser: the server deletes an account listed here that has no player yet
    c.step("getGdkeyAccounts", lambda: c.post("getGdkeyAccounts.nhn", gdkeys=[{"gdkey": c.gdkey}]))
    c.step("userInfoRefresh", lambda: c.post("userInfoRefresh.nhn", requireInfoList=["ywp_user_data", "ywp_user_youkai"]))
    gacha_res = None
    for endpoint in ("map", "getMission", "initGacha", "initCollectMenu", "initWatch",
                     "friend", "getPresentBox", "loginStamp", "initGoku", "initCrystal", "initScoreAttack"):
        res = c.step(endpoint, lambda e=endpoint: c.post(e + ".nhn"))
        if endpoint == "initGacha":
            gacha_res = res
    start = c.step(f"gameStart (stage {args.stage})", lambda: c.post("gameStart.nhn", stageId=args.stage, battleType=0))

    # The steps below change the save: clear the stage, then pull the crank once.
    if isinstance(start, dict) and start.get("requestId"):
        team = [{"youkaiId": y.get("youkaiId"), "damageTotal": 1000, "damageMax": 500, "eraseNum": 50, "eraseSize": 3,
                 "eraseSizeMax": 8, "linkSizeMax": 5, "skillUseNum": 1}
                for y in start.get("userYoukaiList") or [] if isinstance(y, dict)]
        enemies = [{"enemyId": e.get("enemyId"), "deadEndOrder": i + 1, "deadEndType": 1}
                   for i, e in enumerate(start.get("enemyYoukaiList") or []) if isinstance(e, dict)]
        print(f"      stage has {len(enemies)} enemies, team of {len(team)}")
        end = c.step("gameEnd (stage cleared)", lambda: c.post(
            "gameEnd.nhn", requestId=start["requestId"], stageId=args.stage, battleType=0, cheatFlg=0, score=50000,
            clearTimeSec=60, clearTimeLongSec=60000, comboMax=10, damageTotal=5000, eraseNumTotal=200,
            eraseSizeAve=3.0, eraseSizeMax=8, feverTimeNum=1, bonusBlockNum=0, recvDamageTotal=0,
            resultRecvAtkNum=0, resultYoukaiHP=start.get("youkaiHP", 100), scoreLog="", themeResultList=[],
            userYoukaiResultList=team, enemyYoukaiResultList=enemies, ywp_mst_game_const=[]))
        if isinstance(end, dict):
            result = end.get("userGameResultData") or {}
            print(f"      result: exp {result.get('exp')}, money {result.get('money')}, "
                  f"reward yokai {result.get('rewardYoukaiId')}")
    else:
        print("SKIP  gameEnd: gameStart gave no requestId")

    rows = []
    if isinstance(gacha_res, dict) and isinstance(gacha_res.get("ywp_mst_gacha"), str):
        rows = [r.split("|") for r in gacha_res["ywp_mst_gacha"].split("*")]
    # column 3 is the price type (1 = Y-Money), column 5 the price
    paid = sorted((r for r in rows if len(r) > 5 and r[3] == "1" and r[5].isdigit()), key=lambda r: int(r[5]))
    if paid:
        gid, price = int(paid[0][0]), paid[0][5]
        pull = c.step(f"executeGacha (crank {gid}, {price} Y-Money)",
                      lambda: c.post("executeGacha.nhn", gachaId=gid, gachaCnt=1, activeDeckId=1, requestYoukaiId=0,
                                     mstVersionVer=0, token=""))
        if isinstance(pull, dict):
            print(f"      answer keys: {' '.join(sorted(pull))[:300]}")
    else:
        print("SKIP  executeGacha: no Y-Money crank found in initGacha")

    if args.pulls > 0 and paid and args.admin_password:
        tally_pulls(c, args, int(paid[0][0]))
    elif args.pulls > 0:
        print("SKIP  pull tally: needs --admin-password and a Y-Money crank")

    c.step("login again (save still loads)", lambda: c.post("login.nhn"))

    print(f"\n{len(c.failed)} step(s) failed" + (": " + ", ".join(c.failed) if c.failed else ""))
    print("The test account stays on the server; it shows in the admin panel as SmokeTest.")
    return 1 if c.failed else 0


if __name__ == "__main__":
    sys.exit(main())
