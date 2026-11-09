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

`homelab/tools/jp_import.py` ports Yo-kai from the live Japanese game (no login
needed) into your server: about 2,450 that Wibble Wobble never had. Their art
loads in the Wibble Wobble client as-is. What gets adapted:

- **Ranks** above SS (SSS, Z, ZZ, ZZZ, UZ, UZ+) show as SS, since the client
  has no art or rules for them. Their stats are rescaled into the top of the SS
  range, keeping their order: a Japanese UZ+ ends up about 15% above the
  strongest Wibble Wobble SS.
- **Soultimates:** about 660 come over unchanged. The rest use mechanics the
  2017 client has no code for, so they borrow the mechanics, effect and English
  description of the closest Soultimate the client does know (matched on what
  the move does, same tribe preferred). Their own name is kept.

Run it on the server, in the folder that holds `WWR_BACKUP`. It needs
`sudo apt install -y python3-cryptography`, about 2 GB of disk, and Claude Code
signed in for the translation step (uses your Claude plan, no API key):

```
python3 jp_import.py fetch --jp jpdata
python3 jp_import.py translate --jp jpdata --resources WWR_BACKUP/Resources \
    --translations translations.json --all
python3 jp_import.py import --jp jpdata --resources WWR_BACKUP/Resources \
    --data WWR_BACKUP/dataDownload --translations translations.json --all \
    --gacha 500055 --apply
docker compose up -d --build wibwob
```

- `translate` makes about 250 Claude Code calls. If it stops at a usage limit,
  run the same command again later; it continues where it left off.
- `import` without `--apply` is a dry run that shows what it would do.
- `--gacha 500055` adds them to the 4,500 Y-Money Crank-a-kai, by rank
  (`jp_import.py gachas --resources WWR_BACKUP/Resources` lists the machines).
  Leave it out to make them admin-only (`<PIN> 4 <id>`).
- `--limit 200` or `--native-only` import a smaller set. Phones download the new
  files on their next start, so a full import means a big (~1.6 GB) download.
- `starter_translations.json` covers ten hand-translated Yo-kai if you want to
  try a few first with `--ids 2707000 2236900 9000301 9000302 2939000 2116000
  2714000 2683000 2649000 2112000` instead of `--all`.

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
