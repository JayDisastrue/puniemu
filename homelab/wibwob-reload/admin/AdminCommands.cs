// In-game admin commands for a private WibWob Reload server.
//
// Type a command into the game's serial code box (Settings). It is only active
// when ADMIN_PIN is set, and only for codes that start with that PIN followed by
// a space (or any other non-alphanumeric separator), so it never collides with
// the numeric account-link codes the same box is used for.
//
//   <PIN> help                  list commands
//   <PIN> 1 <amount>            set Y-Money
//   <PIN> 2 <amount>            set spirits (stocked energy)
//   <PIN> 3 <itemId> [count]    give an item (default 1)
//   <PIN> 4 <youkaiId>          give a Yo-kai
//
// Changes are made through the server's account cache, so they are saved like
// normal play and are not overwritten by the 60-second save.

using System.Text.RegularExpressions;
using Newtonsoft.Json;
using Puniemu.Src.Server.GameServer.DataClasses;
using Puniemu.Src.Server.GameServer.Logic;
using Puniemu.Src.Server.GameServer.Requests.SerialConfirm.DataClasses;
using Puniemu.Src.TableParser.DataClasses;
using Puniemu.Src.TableParser.Logic;
using udm = Puniemu.Src.UserDataManager.Logic.UserDataManager;

namespace Puniemu.Src.Homelab
{
    public static class AdminCommands
    {
        private const string Help =
            "1 <amount>: set Y-Money\n" +
            "2 <amount>: set spirits\n" +
            "3 <itemId> [count]: give item\n" +
            "4 <youkaiId>: give Yo-kai\n" +
            "No spaces? PIN+command+value";

        /// <summary>Returns true if the code was an admin command (a response has been written).</summary>
        public static async Task<bool> TryHandleAsync(HttpContext ctx, SerialConfirmRequest? req)
        {
            var pin = Environment.GetEnvironmentVariable("ADMIN_PIN")?.Trim();
            var code = req?.SerialCode?.Trim();
            if (string.IsNullOrEmpty(pin) || string.IsNullOrEmpty(code)) return false;

            var parts = Regex.Split(code, "[^0-9A-Za-z]+").Where(p => p.Length > 0).ToArray();
            if (parts.Length == 1)
            {
                // Digits only (number-pad keyboards): never take a pending 6-digit account-link code
                if (int.TryParse(code, out var numeric) && Server.CustomAuth.AuthManager.CodeCache.ContainsKey(numeric))
                    return false;
                parts = DigitsOnly(code, pin);
            }
            if (parts.Length < 2 || parts[0] != pin) return false;

            ctx.Response.ContentType = "application/json";
            var gdkey = req!.Level5UserID;
            if (string.IsNullOrEmpty(gdkey))
            {
                await Reply(ctx, "Could not identify your account.");
                return true;
            }

            try
            {
                var msg = parts[1].ToLowerInvariant() switch
                {
                    "1" => await SetUserData(gdkey, parts, (d, n) => d.YMoney = n, "Y-Money"),
                    "2" => await SetUserData(gdkey, parts, (d, n) => d.Hitodama = n, "Spirits"),
                    "3" => await GiveItem(gdkey, parts),
                    "4" => await GiveYoukai(gdkey, parts),
                    _ => Help,
                };
                Console.WriteLine($"[admin] {gdkey}: {string.Join(' ', parts.Skip(1))} -> {msg.Replace('\n', ' ')}");
                await Reply(ctx, msg);
            }
            catch (Exception ex)
            {
                Console.WriteLine($"[admin] {gdkey}: {string.Join(' ', parts.Skip(1))} failed: {ex}");
                await Reply(ctx, "Command failed:\n" + ex.Message);
            }
            return true;
        }

        /// <summary>
        /// "PIN" + command digit + value, e.g. 482119999999 (Y-Money 9999999), 4821325008099 (item 25008 x99:
        /// item IDs are 5 digits, the rest is the count), 482142152000 (Yo-kai), 48210 (help).
        /// </summary>
        private static string[] DigitsOnly(string code, string pin)
        {
            if (!code.All(char.IsDigit) || !code.StartsWith(pin) || code.Length <= pin.Length) return Array.Empty<string>();
            var cmd = code.Substring(pin.Length, 1);
            var rest = code.Substring(pin.Length + 1);
            if (cmd == "3" && rest.Length > 5)
                return new[] { pin, cmd, rest.Substring(0, 5), rest.Substring(5) };
            return rest.Length > 0 ? new[] { pin, cmd, rest } : new[] { pin, cmd };
        }

        private static async Task<string> SetUserData(string gdkey, string[] parts, Action<YwpUserData, int> set, string label)
        {
            if (parts.Length < 3 || !int.TryParse(parts[2], out var amount) || amount < 0)
                return $"Usage: <PIN> {parts[1]} <amount>";
            var data = await udm.GetYwpUserAsync<YwpUserData>(gdkey, "ywp_user_data")
                       ?? throw new InvalidOperationException("No user data");
            set(data, amount);
            await udm.SetYwpUserAsync(gdkey, "ywp_user_data", data);
            return $"{label} set to {amount}.\nRestart the game to see it.";
        }

        private static async Task<string> GiveItem(string gdkey, string[] parts)
        {
            if (parts.Length < 3 || !long.TryParse(parts[2], out var itemId))
                return "Usage: <PIN> 3 <itemId> [count]";
            var count = parts.Length > 3 && int.TryParse(parts[3], out var c) && c > 0 ? c : 1;
            var name = MasterName("ywp_mst_item", itemId.ToString(), nameColumn: 2);
            if (name == null) return $"Item {itemId} does not exist.";

            var items = new TableParser<YwpUserItem>(await udm.GetYwpUserAsync<string>(gdkey, "ywp_user_item"));
            items = ItemManager.AddItem(items, itemId, count);
            await udm.SetYwpUserAsync(gdkey, "ywp_user_item", items.ToString());
            return $"Gave {count} x {name}.\nRestart the game to see it.";
        }

        private static async Task<string> GiveYoukai(string gdkey, string[] parts)
        {
            if (parts.Length < 3 || !long.TryParse(parts[2], out var youkaiId))
                return "Usage: <PIN> 4 <youkaiId>";
            var name = MasterName("ywp_mst_youkai", youkaiId.ToString(), nameColumn: 1);
            if (name == null) return $"Yo-kai {youkaiId} does not exist.";

            var userYokai = new TableParser<YwpUserYoukai>(await udm.GetYwpUserAsync<string>(gdkey, "ywp_user_youkai"));
            var userSkill = new TableParser<YwpUserYoukaiSkill>(await udm.GetYwpUserAsync<string>(gdkey, "ywp_user_youkai_skill"));
            var userBonus = new TableParser<YwpUserYoukaiBonusEffect>(await udm.GetYwpUserAsync<string>(gdkey, "ywp_user_youkai_bonus_effect"));
            var userDict = new TableParser<YwpUserDictionary>(await udm.GetYwpUserAsync<string>(gdkey, "ywp_user_dictionary"));

            await YoukaiManager.AddYoukai(userYokai, youkaiId, userSkill, userBonus, gdkey);
            DictionaryManager.EditDictionary(ref userDict, youkaiId, true, true);

            await udm.SetYwpUserAsync(gdkey, "ywp_user_youkai", userYokai.ToString());
            await udm.SetYwpUserAsync(gdkey, "ywp_user_youkai_skill", userSkill.ToString());
            await udm.SetYwpUserAsync(gdkey, "ywp_user_youkai_bonus_effect", userBonus.ToString());
            await udm.SetYwpUserAsync(gdkey, "ywp_user_dictionary", userDict.ToString());
            return $"Gave {name}.\nRestart the game to see it.";
        }

        /// <summary>Looks up a row's display name in a master table; null if the ID doesn't exist.</summary>
        private static string? MasterName(string table, string id, int nameColumn)
        {
            if (!DataManager.Logic.DataManager.GameDataManager.GamedataCache.TryGetValue(table, out var raw)) return null;
            var data = raw.TrimStart().StartsWith("{")
                ? JsonConvert.DeserializeObject<Dictionary<string, object>>(raw)!["tableData"].ToString()!
                : raw;
            foreach (var row in data.Split('*'))
            {
                var cols = row.Split('|');
                if (cols[0] == id) return cols.Length > nameColumn && cols[nameColumn].Length > 0 ? cols[nameColumn] : id;
            }
            return null;
        }

        private static Task Reply(HttpContext ctx, string message)
        {
            var res = new MsgBoxResponse(message, "Admin");
            return ctx.Response.WriteAsync(NHNCrypt.Logic.NHNCrypt.EncryptResponse(JsonConvert.SerializeObject(res)));
        }
    }
}
