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
- A domain on Cloudflare DNS, with a name of **16 characters or fewer**
  (e.g. `wib.example.xyz`). The client patch overwrites the server address in place,
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

Progress is saved automatically every `SAVE_INTERVAL_SECONDS` (10 by default),
and on any normal `docker compose stop`, `restart`, `down` or host reboot. Only a
crash, power cut or `docker kill` can lose the last few seconds.

Edit accounts (Y-Money, spirits, items) with:
```
docker compose exec db psql -U puni puniemu
```
The server log (`docker compose logs server`) prints the `gdkey` of each account.

## Game client (Android and iOS)

The builds from https://wibblewobble.de/en/ (currently Spanish only) work as a
base for both platforms: the IPA is already decrypted. They point at that
site's server; `homelab/tools/patch_client.py` repoints them at yours.

Your domain must be **16 characters or fewer** (e.g. `wib.example.xyz`), so it
fits every place the address is stored without changing file sizes.

1. Check a file (optional; shows encryption status and server addresses):
   `python3 homelab/tools/inspect_client.py WibbleWobble.ipa`
2. Patch:
   `python3 homelab/tools/patch_client.py WibbleWobble.apk wib.example.xyz`
   `python3 homelab/tools/patch_client.py WibbleWobble.ipa wib.example.xyz`
3. Android: sign, then install with "Install with Options" (Full Application,
   Bypass Low Target SDK Block):
   `java -jar uber-apk-signer-1.3.0.jar -a WibbleWobble-patched.apk --allowResign`
4. iOS: sideload `WibbleWobble-patched.ipa` with Sideloadly or AltStore. With a
   free Apple ID it must be re-signed every 7 days (AltStore can do this
   automatically).

The phone must be connected to Tailscale while playing.

For the original NHN APK or the "Reloaded" build, the script also recognises
their addresses; see the gist above for the manual hex-editor method.
