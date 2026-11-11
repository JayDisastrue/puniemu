# Puniemu: working notes for Claude

Private-server emulator for Yo-kai Watch Puni Puni (C#, ASP.NET Core, .NET 8, Postgres).
Owner's goal: the current Japanese game (client 4.177.0) on their own server, with English
text and an admin panel. Work branch: `claude/dazzling-hypatia-ymn8wv`.

## Where things are on the owner's server

- Repo: `/opt/homelab/puni`. Compose file: `/opt/homelab/docker-compose.yml` (services `puni`, `puni-db`).
- `Resources/` (gitignored): game master tables, compiled INTO the image. Any change needs a rebuild.
- `Resources.from-wibwob.list`: files still borrowed from the 2018 English game (stand-ins to replace).
- `translations/strings.json` (gitignored): Japanese -> English dictionary.
- `dataDownload/eal/` (gitignored): all 74,734 game assets, served by the server at `/eal`.
- `~/puni.flows`: capture of a real play session. `~/puni-shapes.json`: value-free field layouts from it.

## The loop

```bash
cd /opt/homelab && sudo docker compose up -d --build puni && sleep 5
cd /opt/homelab/puni && python3 Tools/smoke_test.py --server http://127.0.0.1:8086 --app-ver 4.177.0 --compare ~/puni-shapes.json
sudo docker compose -f /opt/homelab/docker-compose.yml logs --since 3m puni | grep -A4 "Exception:"
```

`smoke_test.py` plays the client's part: account, login, menus, a stage start and clear, a crank
pull. `--compare` lists where replies differ from the real server's. `--pulls N --admin-password`
tallies crank pulls. `--stage ID` picks the stage. A stage can answer "You don't have the pass":
that is a ticket-gated stage, not a bug.

Back up before touching data: `sudo tar czf ~/puni-resources-$(date +%F-%H%M).tgz Resources Resources.from-wibwob.list translations`

## Tools (all in `Tools/`, each has `--help`, most have `--dry-run`)

| Tool | Does |
|---|---|
| `fetch_puni_resources.py` | Master tables from the open endpoint |
| `fetch_puni_assets.py` | Asset download into `dataDownload/eal/` |
| `captures_to_resources.py` | Capture file -> `Resources/`; `--show NAME` prints a request's layout without values |
| `inspect_capture.py` | Request types and played stages in a capture, no account data |
| `build_gacha_pool.py` | Crank pools: odds per rank, item tiers, pity |
| `build_stage_data.py` | Stage enemy line-ups from the tables, scored against a capture |
| `build_name_table.py` | English Yo-kai names from the wiki, by Medallium number |
| `translate_resources.py` | `scan` collects Japanese strings, `apply` writes English into `Resources/` |
| `build_image_gallery.py` | Browsable pages of images that likely contain text |

## Facts already established (do not re-derive)

- Wire format: AES-ECB + gzip, key and digest salt in `fetch_puni_resources.py`. Still valid for 4.177.0.
- Tables are `a|b*c|d` text. Files store them as `{"tableData": "..."}`, some as `{"data": [...]}`;
  the real server often sends them bare. `captures_to_resources.py` handles the wrapping.
- `ywp_mst_youkai`: col 0 id, 1 name, 3 rank (1 E .. 13 UZ+, 14 UZ++, 0 unranked), 5 level type,
  7 max level, 14 Medallium number, 31 kana reading. Max level 0 = enemy/boss entry, not ownable.
- Stage -> enemies: enemy id = stage id + 2 digits (story), or map + 2-digit stage + 1 digit
  (8-digit stage ids); a line-up stops at the first gap in numbering. Stage col 12 names an enemy
  set holding the first enemy only. Cols 8-10 are the star conditions.
- After a stage or crank pull the real server sends changed rows as `ywp_user_*_diff`.
- Crank pool contents, odds, event rules and schedules never leave NHN's servers. They are
  authored here, not fetched.

## State

Working under the smoke test: accounts, login, menus, stages (all 1,570 have line-ups), crank
(odds, UZ++, pity, six book tiers), admin panel at `/admin`. English names for 97% of Yo-kai are in
the dictionary but NOT yet applied to `Resources/`.

Backlog, in order:
1. `login`: the real reply has ~18 fields the emulator lacks and omits 5 it sends (`--show login`).
2. Handlers every player hits: `receivePresentBox`, `missionRewardAll`, `updateCollectMenu`.
3. Remaining captured-but-unhandled requests (raid boss, shooting game, event quests, rankings, ...).
4. Translation: stage conditions by template (1.77M chars, highly repetitive), then the rest
   (~650k chars) with names locked in; then apply and rebuild.
5. Images: Soultimate banners from data, then labels and buttons (transparent-background lettering).

## Rules

- `~/puni.flows` holds the owner's account tokens and save. Never print, copy or commit its
  contents. Use the tools above, which only output names, ids and layouts.
- Do not script logins or any new traffic against the live game servers. The two fetch tools are
  the only code that talks to them.
- Modifying or analysing the game client (APK/IPA) is out of scope for this work.
- Other homelab services share this machine and compose file. Only touch `puni` and `puni-db`.
- Match each file's existing line endings and BOM when editing C# (many are CRLF).
- Verify with the loop above before saying something works, and report what was not tested.
