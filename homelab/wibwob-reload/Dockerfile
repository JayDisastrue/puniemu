# Builds the WibWob Reload (WibWobPadaBoom 1.1) server.
# Copy this folder's files into the extracted WibWobPadaBoom folder first.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY Puniemu.csproj .
RUN dotnet restore Puniemu.csproj
COPY Src Src
COPY Properties Properties
COPY WWR_BACKUP/Resources WWR_BACKUP/Resources
# Accept a comma-separated GameVersion list so 4.0.6 (Reload APK), 4.0.7 (iOS)
# and 4.0.8 (wibblewobble.de APK) clients can all log in.
RUN F=Src/Server/GameServer/Requests/Init/Init/Logic/InitHandler.cs \
 && grep -q '(string)appVer != DataManager.Logic.DataManager.GameVersion' $F \
 && sed -i 's#(string)appVer != DataManager.Logic.DataManager.GameVersion#!(DataManager.Logic.DataManager.GameVersion ?? "").Split(",").Select(v => v.Trim()).Contains((string)appVer)#' $F
# Homelab additions: in-game admin commands (ADMIN_PIN) and weekly Yo-kai room rotation
COPY admin/ Src/Homelab/
RUN F=Src/Program.cs \
 && grep -q '        UserDataManager.Logic.UserDataManager.Initialize();' $F \
 && sed -i '/^        UserDataManager.Logic.UserDataManager.Initialize();/a\        Puniemu.Src.Homelab.RoomRotation.Start();' $F
RUN F=Src/Server/GameServer/Requests/SerialConfirm/Logic/SerialConfirmHandler.cs \
 && grep -q 'var deserialized = JsonConvert.DeserializeObject<SerialConfirmRequest>(requestJsonString!);' $F \
 && sed -i '/var deserialized = JsonConvert.DeserializeObject<SerialConfirmRequest>(requestJsonString!);/a\            if (await Puniemu.Src.Homelab.AdminCommands.TryHandleAsync(ctx, deserialized)) return;' $F
RUN dotnet publish Puniemu.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app .
# Game files and custom Yo-kai are mounted at runtime (see docker-compose.yml)
ENV Urls=http://0.0.0.0:80
EXPOSE 80
ENTRYPOINT ["dotnet", "Puniemu.dll"]
