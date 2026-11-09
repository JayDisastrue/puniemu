# WibWob Reload on a homelab (Docker, private over Tailscale)

Runs the WibWob Reload server (WibWobPadaBoom 1.1 by TheC0mmand) in Docker:
Postgres plus the game server, which also serves the game files. Plain HTTP on
port 80, reachable only from your own devices over Tailscale. No domain or
certificate needed.

Source package: https://github.com/TheC0mmand/WibWobPadaBoom/tree/1.1
(download the V1.1 ZIP from the MEGA link in its README).

## Server

1. Extract `WibWobPadaBoom_1.1.zip` on the homelab.
2. Copy everything in this folder (`Dockerfile`, `.dockerignore`,
   `docker-compose.yml`, `schema.sql`, `.env.example`, `admin/`) into the
   extracted `WibWobPadaBoom/` folder.
3. `mkdir -p CUSTOM_YOKAI` (the compose file mounts it; empty is fine).
4. `cp .env.example .env` and set a database password.
5. `docker compose up -d --build`
6. From a phone on Tailscale, open `http://<homelab address>/eal/help.html`.
   Don't patch the game until this page loads.

The database starts empty, from `schema.sql`. Do **not** import
`WWR_BACKUP/backup_nomail.sql`: it is a ~900 MB dump of other players'
accounts from someone else's server. Your private server doesn't need it, and
those strangers would show up in friend search and rankings.

Accounts are saved every 60 seconds and on any normal `docker compose stop`,
`restart`, `down` or host reboot.

## Admin commands (in game)

Set `ADMIN_PIN` in `.env` (any number only you know) and rebuild. Then in the
game open Settings → the serial code box and type the PIN, a space, and a
command. Commands without your PIN are handled normally.

| Type | Does |
|---|---|
| `<PIN> help` | lists the commands |
| `<PIN> 1 <amount>` | sets Y-Money |
| `<PIN> 2 <amount>` | sets spirits |
| `<PIN> 3 <itemId> [count]` | gives an item |
| `<PIN> 4 <youkaiId>` | gives a Yo-kai |

Restart the game afterwards to see the change. Item and Yo-kai IDs:
`python3 homelab/tools/list_ids.py WWR_BACKUP/Resources ids.md`.

## Weekly Yo-kai rooms

The Yo-kai rooms (The Last Nyanmurai Room, Platinos Room, and so on) rotate:
`ROOMS_PER_WEEK` of them (default 2) are open each week, switching Monday
00:00 in `ROTATION_TIMEZONE`. The server log shows which with `[rooms]`. Story
maps and Mimikin Heights stay open. `ROOM_ROTATION=off` opens every room.
`ROOM_ROTATION_MAPS=5001,5004,...` sets your own order.

## Yo-kai from Japanese Puni Puni

`homelab/tools/jp_import.py` pulls Yo-kai from the live Japanese game (no login
needed) into your server. Their art works in the Wibble Wobble client as-is;
only the text needs English. Run it on the server, in the folder that holds
`WWR_BACKUP` (needs `sudo apt install -y python3-cryptography`):

```
python3 jp_import.py fetch --jp jpdata
python3 jp_import.py list --jp jpdata --resources WWR_BACKUP/Resources
python3 jp_import.py import --jp jpdata --resources WWR_BACKUP/Resources \
    --data WWR_BACKUP/dataDownload --translations starter_translations.json \
    --ids 2707000 2236900 9000301 9000302 2939000 2116000 2714000 2683000 2649000 2112000 --apply
docker compose up -d --build wibwob
```

`starter_translations.json` covers those ten (Hovernyan Ace, Hovernyan S,
Kyubi Shadow/Light, Wobblehover, Benkei, Daikoku, Mecha Kyubi, Ashura,
General Genma). Give them to yourself with `<PIN> 4 <id>`.

For more, either write English into a template
(`jp_import.py template --jp jpdata --translations mine.json --ids ...`) or let
Claude translate (`pip install anthropic`, set `ANTHROPIC_API_KEY`, then
`jp_import.py translate ... --ids ...`; defaults to Claude Haiku 5.5, about a
cent per few Yo-kai).

Limits: `list` shows only Yo-kai whose Soultimate type the old client knows
(about 680 of 2,467); newer types are refused because they will likely break.
Ranks above SS are imported as SS. Imported Yo-kai are not in any
Crank-a-kai; use the admin command.

Edit the database directly only while the server is stopped: it keeps active
accounts in memory and saves them every 60 seconds, overwriting outside edits.
```
docker compose exec db psql -U wibwob wibwob
```

## Your server address

The game stores the server address in fixed-size slots, so it must be short.
The server runs on port 80, so no port is needed. Use one of:

- **Tailscale IP**, if it is 14 characters or fewer (`tailscale ip -4`).
  If it's longer, change it in the Tailscale admin console: Machines → the
  homelab → Edit machine IPv4, e.g. `100.64.0.10`.
- **MagicDNS short name** (e.g. `homelab`), if MagicDNS is on.

## Android

Use `APK/WibWobPadaBoom.apk` from the package (English). It only contains
32-bit libraries, so it won't install on 64-bit-only phones (e.g. Pixel 7 and
newer). On those, patch the English APK from https://wibblewobble.de/en/
instead, which is 64-bit; the commands are the same.

```
python3 homelab/tools/patch_client.py WibWobPadaBoom.apk 100.64.0.10
java -jar uber-apk-signer-1.3.0.jar -a WibWobPadaBoom-patched.apk --allowResign
```

`patch_client.py` is in the Puniemu repo (`homelab/tools/`). The package's own
`CUSTOM_APK_BUILDER` (Windows) does the same job if you prefer it; give it your
homelab address and port 80.

## iOS (untested)

WibWob Reload has no IPA. The English IPA from https://wibblewobble.de/en/ is
decrypted and can be repointed the same way:

```
python3 homelab/tools/patch_client.py WibbleWobble-en.ipa 100.64.0.10
```

Sideload the result with Sideloadly or AltStore (free Apple ID: re-sign every
7 days). If the game shows a network error while the help page above loads
in Safari, that build probably requires HTTPS, which needs a reverse proxy
with a real certificate in front of this server.
