# Puniemu

A WIP server emulator for Yo-kai Watch Puni Puni.

<p align="center">
<img src=https://i.imgur.com/zO49hMu.png alt=logo width=320>
</p>

## What is this? 👀

Essentially, this is a private server for *Yo-kai Watch Puni Puni* written in C#. It can be hosted by anyone, anywhere as a drop-in replacement for NHN's servers. This allows everyone to play even after the servers shut down. Additionally, you can have full control over your experience by modifying the code.

## Running it 🏃

You need the .NET 8 SDK, Docker (for Postgres), and three things this repo does not ship:

1. `Resources/` - the game master data tables (`ywp_mst_*.txt`, `stage_data.txt`, `gacha_pool.txt`, ...). They are embedded into the build, so they must be in place before `dotnet build`. The server answers nothing useful without them.
2. The data download files (the `eal` folder), served by `Tools/dataDownloadServerEmulator.py` or any static file host.
3. A game client patched to talk to your server instead of NHN's.

Then:

```bash
docker compose up -d
```

```bash
cp appsettings.example.json appsettings.json
```

```bash
dotnet run -c Release --urls http://0.0.0.0:8080
```

In `appsettings.json`:

- `IsWibWob`: `true` for the English client (*Wibble Wobble*), `false` for the Japanese client (*Puni Puni*). `Resources/` must be the matching data set.
- `GameVersion`: must equal the `appVer` your client sends, or login is refused.
- `DataDownloadURL`: where the client fetches the data download from.
- `Cheats:MinYMoney` / `Cheats:MinHitodama`: on every login, Y-Money and spirit are topped up to at least these amounts. Set both to `0` to play legit.

## DISCLAIMERS 🚫

Please note that this project is completely non-profit. As such, in-app purchases are completely disabled.

The project is in no way affiliated with NHN. We do not intend to infringe on their copyright in any way, shape or form.

## Credits 🎬

- Zura - Main dev
- DarkCraft - Main dev
- wibwob_yt - Dev
- onepiecefreak3 - Reverse engineering help
- kuronosuFear - Reverse engineering help
- picky_x_keizen - Logo
