// Weekly rotation of the Yo-kai rooms (maps with mapType 4) for a private
// WibWob Reload server.
//
// Each week (Monday 00:00 in ROTATION_TIMEZONE, default UTC) the next
// ROOMS_PER_WEEK rooms open and the rest close. Every request that serves the
// map table reads the in-memory copy this class rewrites, so the whole server
// switches over together. Main story maps and other event maps are untouched.
//
// Settings (environment variables):
//   ROOM_ROTATION        "off" disables it (all rooms stay open, as before)
//   ROOMS_PER_WEEK       rooms open at once, default 2
//   ROOM_ROTATION_MAPS   comma-separated mapIds in rotation order; default:
//                        every mapType 4 map except ones named "Test..."
//   ROTATION_TIMEZONE    IANA zone for the Monday boundary, default UTC

using System.Collections.Concurrent;
using System.Reflection;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Puniemu.Src.Homelab
{
    public static class RoomRotation
    {
        private const string Table = "ywp_mst_map";
        private const string DateFormat = "yyyy-MM-dd HH:mm:ss";
        // A Monday; week numbers count from here
        private static readonly DateTime Epoch = new(2024, 1, 1);

        private static string? _original;
        private static long _appliedWeek = long.MinValue;
        private static Timer? _timer;

        public static void Start()
        {
            if (string.Equals(Environment.GetEnvironmentVariable("ROOM_ROTATION"), "off", StringComparison.OrdinalIgnoreCase))
            {
                Console.WriteLine("[rooms] rotation off");
                return;
            }
            var cache = DataManager.Logic.DataManager.GameDataManager.GamedataCache;
            if (!cache.TryGetValue(Table, out _original))
            {
                Console.WriteLine("[rooms] no ywp_mst_map table; rotation off");
                return;
            }
            Apply();
            _timer = new Timer(_ => Apply(), null, TimeSpan.FromMinutes(1), TimeSpan.FromMinutes(1));
        }

        private static void Apply() => Apply(DateTime.UtcNow);

        internal static void Apply(DateTime utcNow)
        {
            try
            {
                var tz = TimeZone();
                var localNow = TimeZoneInfo.ConvertTimeFromUtc(utcNow, tz);
                var week = (long)Math.Floor((localNow.Date - Epoch).TotalDays / 7);
                if (week == _appliedWeek) return;

                var root = JObject.Parse(_original!);
                var maps = (JArray)root["data"]!;
                var rooms = RotationOrder(maps);
                if (rooms.Count == 0)
                {
                    Console.WriteLine("[rooms] no rooms found; rotation off");
                    _timer?.Dispose();
                    return;
                }

                var perWeek = Math.Clamp(EnvInt("ROOMS_PER_WEEK", 2), 1, rooms.Count);
                var open = new HashSet<long>();
                for (var i = 0; i < perWeek; i++)
                    open.Add(rooms[(int)(((week * perWeek + i) % rooms.Count + rooms.Count) % rooms.Count)]);

                var weekStartLocal = Epoch.AddDays(week * 7);
                var openUtc = TimeZoneInfo.ConvertTimeToUtc(weekStartLocal, tz);
                var closeUtc = TimeZoneInfo.ConvertTimeToUtc(weekStartLocal.AddDays(7).AddSeconds(-1), tz);
                // Dates in the table are server-local; the container runs in UTC
                var openDt = openUtc.ToString(DateFormat);
                var closeDt = closeUtc.ToString(DateFormat);
                var closedDt = openUtc.AddSeconds(-1).ToString(DateFormat);

                var names = new List<string>();
                foreach (var map in maps.OfType<JObject>())
                {
                    var id = map.Value<long>("mapId");
                    if (!rooms.Contains(id)) continue;
                    if (open.Contains(id))
                    {
                        map["openDt"] = openDt;
                        map["closeDt"] = closeDt;
                        names.Add(map.Value<string>("mapName") ?? id.ToString());
                    }
                    else
                    {
                        map["openDt"] = "2015-01-01 00:00:00";
                        map["closeDt"] = closedDt;
                    }
                }

                DataManager.Logic.DataManager.GameDataManager.GamedataCache[Table] = root.ToString(Formatting.None);
                ClearGetMasterCache();
                _appliedWeek = week;
                Console.WriteLine($"[rooms] week of {weekStartLocal:yyyy-MM-dd}: open {string.Join(", ", names)} until {closeDt} UTC");
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[rooms] rotation failed, leaving maps as they are: {ex.Message}");
            }
        }

        private static List<long> RotationOrder(JArray maps)
        {
            var configured = Environment.GetEnvironmentVariable("ROOM_ROTATION_MAPS");
            if (!string.IsNullOrWhiteSpace(configured))
                return configured.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                    .Select(long.Parse).ToList();
            return maps.OfType<JObject>()
                .Where(m => m.Value<int>("mapType") == 4
                            && !(m.Value<string>("mapName") ?? "").StartsWith("Test", StringComparison.OrdinalIgnoreCase))
                .OrderBy(m => m.Value<int?>("sort") ?? 0).ThenBy(m => m.Value<long>("mapId"))
                .Select(m => m.Value<long>("mapId"))
                .ToList();
        }

        // GetMasterHandler keeps its own parsed copy of each table; drop the map entry so it re-reads ours.
        private static void ClearGetMasterCache()
        {
            var type = Type.GetType("Puniemu.Src.Server.GameServer.Requests.GetMaster.Logic.GetMasterHandler");
            var field = type?.GetField("UnmarshalCache", BindingFlags.NonPublic | BindingFlags.Static);
            if (field?.GetValue(null) is ConcurrentDictionary<string, object> cache)
                cache.TryRemove(Table, out _);
        }

        private static TimeZoneInfo TimeZone()
        {
            var id = Environment.GetEnvironmentVariable("ROTATION_TIMEZONE");
            if (string.IsNullOrWhiteSpace(id)) return TimeZoneInfo.Utc;
            try { return TimeZoneInfo.FindSystemTimeZoneById(id); }
            catch { Console.WriteLine($"[rooms] unknown ROTATION_TIMEZONE '{id}', using UTC"); return TimeZoneInfo.Utc; }
        }

        private static int EnvInt(string name, int fallback) =>
            int.TryParse(Environment.GetEnvironmentVariable(name), out var v) ? v : fallback;
    }
}
