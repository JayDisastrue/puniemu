# Build. Resources/ (game master data) must exist in the build context:
# it is embedded into the assembly at compile time.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY Puniemu.csproj ./
RUN dotnet restore
COPY . .
RUN test -n "$(ls Resources/*.txt 2>/dev/null)" || (echo "Resources/*.txt is missing: put the game master data in Resources/ before building" >&2; exit 1)
RUN dotnet publish Puniemu.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app ./
ENV ASPNETCORE_HTTP_PORTS=8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "Puniemu.dll"]
