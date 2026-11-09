# Resources/*.txt must exist before building: the game tables are embedded into the binary.
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY Puniemu.csproj .
RUN dotnet restore Puniemu.csproj
COPY . .
RUN dotnet publish Puniemu.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app .
ENV ASPNETCORE_URLS=http://0.0.0.0:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "Puniemu.dll"]
