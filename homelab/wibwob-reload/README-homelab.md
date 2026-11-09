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
   `docker-compose.yml`, `schema.sql`, `.env.example`) into the extracted
   `WibWobPadaBoom/` folder.
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

Edit accounts:
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
