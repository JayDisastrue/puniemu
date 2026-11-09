# Private Wibble Wobble server on a homelab

Runs Puniemu, Postgres and Caddy with Docker Compose. The server is only reachable
over your Tailscale network, but still has a valid HTTPS certificate, which the
patched APK requires.

Based on the Windows/ngrok guide by Amumis:
https://gist.github.com/Amumis/75fa45025b42079816f04699cef352d0

## What you need

- A Linux box with Docker and Docker Compose, joined to your tailnet.
- The `Resources/` and `dataDownload/` folders. These are not in the repo and
  are not distributed here; get them from the Puniemu community.
- A domain on Cloudflare DNS, with a name of **33 characters or fewer**
  (e.g. `puni.example.xyz`). The APK patch overwrites the server address in place,
  so it cannot be longer than that.
- A Cloudflare API token with `Zone:DNS:Edit` for that zone (for the certificate).

## Server

1. Put the data in the repo root:
   ```
   Resources/*.txt          # embedded at build time
   dataDownload/help.html   # plus the game asset files
   ```
2. In Cloudflare, create an **A record** for your domain pointing at the homelab's
   Tailscale IP (`tailscale ip -4`), **DNS only** (grey cloud, not proxied).
3. `cp .env.example .env` and fill it in.
4. `docker compose up -d --build`
5. From a device on your tailnet, open `https://<your domain>/help/inquiry/top.nhn`.
   A page should load with a valid certificate.

The database schema is applied automatically on first start.

Stop with `docker compose stop`, not `kill`: accounts live in memory and are
written to Postgres on shutdown.

Edit accounts (Y-Money, spirits, items) with:
```
docker compose exec db psql -U puni puniemu
```
The server log (`docker compose logs server`) prints the `gdkey` of each account.

## APK

Follow section 3 of the gist above, using your domain instead of the ngrok one:

1. Open the Wibble Wobble APK in Apk Editor Studio, "Open Contents".
2. In `lib/armeabi-v7a/libSGF.so` (and again in `lib/x86/libSGF.so`), use a hex
   editor to find the first `https://` and overwrite the hostname after it
   (`s-ywp-us-gameserver.hangame.co.jp`, or `wibwob.ddns.net////...` in Reloaded)
   with your domain. Overwrite only; do not insert or delete bytes. Pad any
   leftover characters the same way the original does.
3. In `res/xml/hsp_launching_zone.xml`, set every `address` to `https://<your domain>/hsp`.
4. Export, then sign:
   `java -jar uber-apk-signer-1.3.0.jar -a your.apk --allowResign`
5. Install with "Install with Options" (Full Application, Grant All Permissions,
   Bypass Low Target SDK Block).

The phone must be connected to Tailscale while playing.
