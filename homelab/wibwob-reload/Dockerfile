# Builds the WibWob Reload (WibWobPadaBoom 1.1) server.
# Copy this folder's files into the extracted WibWobPadaBoom folder first.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY Puniemu.csproj .
RUN dotnet restore Puniemu.csproj
COPY Src Src
COPY Properties Properties
COPY WWR_BACKUP/Resources WWR_BACKUP/Resources
RUN dotnet publish Puniemu.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app .
# Game files and custom Yo-kai are mounted at runtime (see docker-compose.yml)
ENV Urls=http://0.0.0.0:80
EXPOSE 80
ENTRYPOINT ["dotnet", "Puniemu.dll"]
