using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using Puniemu.Src.Server.GameServer.DataClasses;
using Puniemu.Src.Server.GameServer.DataClasses.Mission;
using Puniemu.Src.Server.GameServer.Logic;
using Puniemu.Src.TableParser.DataClasses;
using Puniemu.Src.TableParser.Logic;
using UserData = Puniemu.Src.UserDataManager.Logic.UserDataManager;

namespace Puniemu.Src.Server.Admin
{
    // Password-protected admin panel. Lets the server owner edit any account
    // (currencies, Yo-kai, items) from a browser. Regular players are untouched.
    // Disabled entirely unless "AdminPassword" is set in appsettings.
    public static class AdminHandler
    {
        private const int MAX_SOUL_LEVEL = 7;
        private const int MAX_SOUL_POINTS = 34000;
        private const int MAX_CURRENCY = 99999999;

        public static void Map(WebApplication app)
        {
            app.MapGet("/admin", async ctx =>
            {
                if (!Enabled) { ctx.Response.StatusCode = 404; return; }
                ctx.Response.ContentType = "text/html; charset=utf-8";
                ctx.Response.Headers.CacheControl = "no-store";
                await ctx.Response.WriteAsync(AdminPage.Html);
            });
            app.MapGet("/admin/api/catalog", ctx => Run(ctx, _ => Task.FromResult<object>(GetCatalog())));
            app.MapGet("/admin/api/accounts", ctx => Run(ctx, async _ => await UserData.ListAccountsAsync(ctx.Request.Query["q"].ToString())));
            app.MapPost("/admin/api/account", ctx => Run(ctx, async body => await DescribeAccount(Gdkey(body))));
            app.MapPost("/admin/api/currency", ctx => Run(ctx, SetCurrency));
            app.MapPost("/admin/api/yokai", ctx => Run(ctx, GiveYokai));
            app.MapPost("/admin/api/yokai/all", ctx => Run(ctx, GiveAllYokai));
            app.MapPost("/admin/api/item", ctx => Run(ctx, GiveItem));
        }

        private static bool Enabled => !string.IsNullOrEmpty(DataManager.Logic.DataManager.AdminPassword);

        private static bool IsAuthorized(HttpContext ctx)
        {
            var expected = Encoding.UTF8.GetBytes(DataManager.Logic.DataManager.AdminPassword!);
            var given = Encoding.UTF8.GetBytes(ctx.Request.Headers["X-Admin-Password"].ToString());
            return CryptographicOperations.FixedTimeEquals(SHA256.HashData(expected), SHA256.HashData(given));
        }

        private class AdminException : Exception
        {
            public AdminException(string message) : base(message) { }
        }

        private static async Task Run(HttpContext ctx, Func<JObject, Task<object>> action)
        {
            if (!Enabled) { ctx.Response.StatusCode = 404; return; }
            ctx.Response.ContentType = "application/json; charset=utf-8";
            ctx.Response.Headers.CacheControl = "no-store";
            if (!IsAuthorized(ctx))
            {
                //Slow down password guessing
                await Task.Delay(1000);
                ctx.Response.StatusCode = 401;
                await ctx.Response.WriteAsync(JsonConvert.SerializeObject(new { error = "Wrong admin password." }));
                return;
            }
            try
            {
                var body = new JObject();
                if (HttpMethods.IsPost(ctx.Request.Method))
                {
                    using var reader = new StreamReader(ctx.Request.Body, Encoding.UTF8);
                    var text = await reader.ReadToEndAsync();
                    if (!string.IsNullOrWhiteSpace(text)) body = JObject.Parse(text);
                }
                var result = await action(body);
                await ctx.Response.WriteAsync(JsonConvert.SerializeObject(result));
            }
            catch (Exception ex) when (ex is AdminException || ex is JsonException || ex is FormatException || ex is OverflowException)
            {
                ctx.Response.StatusCode = 400;
                await ctx.Response.WriteAsync(JsonConvert.SerializeObject(new { error = ex.Message }));
            }
        }

        private static string Gdkey(JObject body)
        {
            var gdkey = (string?)body["gdkey"];
            if (string.IsNullOrEmpty(gdkey)) throw new AdminException("No account selected.");
            return gdkey;
        }

        private static async Task<YwpUserData> LoadUserData(string gdkey)
        {
            var acc = await UserData.GetAccountFromGdkeyAsync(gdkey);
            if (acc == null) throw new AdminException("Account not found.");
            var userData = acc.YwpUserTables == null ? null : await UserData.GetYwpUserAsync<YwpUserData>(gdkey, "ywp_user_data");
            if (userData == null) throw new AdminException("This account has not finished character creation yet.");
            return userData;
        }

        private static async Task<object> DescribeAccount(string gdkey)
        {
            var userData = await LoadUserData(gdkey);
            var yokai = new TableParser<YwpUserYoukai>(await UserData.GetYwpUserAsync<string>(gdkey, "ywp_user_youkai"));
            return new
            {
                gdkey,
                playerName = userData.PlayerName,
                characterId = userData.CharacterID,
                ymoney = userData.YMoney,
                hitodama = userData.Hitodama,
                freeHitodama = userData.FreeHitodama,
                yokaiCount = yokai.Items.Count
            };
        }

        private static async Task<object> SetCurrency(JObject body)
        {
            var gdkey = Gdkey(body);
            var userData = await LoadUserData(gdkey);
            if (body["ymoney"] != null && body["ymoney"]!.Type != JTokenType.Null)
                userData.YMoney = (int)Math.Clamp((long)body["ymoney"]!, 0, MAX_CURRENCY);
            if (body["hitodama"] != null && body["hitodama"]!.Type != JTokenType.Null)
                userData.Hitodama = (int)Math.Clamp((long)body["hitodama"]!, 0, MAX_CURRENCY);
            await UserData.SetYwpUserAsync(gdkey, "ywp_user_data", userData);
            return await DescribeAccount(gdkey);
        }

        private static async Task<object> GiveYokai(JObject body)
        {
            var gdkey = Gdkey(body);
            await LoadUserData(gdkey);
            long youkaiId = (long)(body["youkaiId"] ?? throw new AdminException("No Yo-kai chosen."));
            bool max = (bool?)body["max"] ?? false;
            var given = await GiveYokaiList(gdkey, new List<long> { youkaiId }, max);
            if (given == 0) throw new AdminException($"Yo-kai {youkaiId} does not exist in the master data.");
            return await DescribeAccount(gdkey);
        }

        private static async Task<object> GiveAllYokai(JObject body)
        {
            var gdkey = Gdkey(body);
            await LoadUserData(gdkey);
            bool max = (bool?)body["max"] ?? false;
            //Max level 0 marks enemy and boss entries, rank 0 marks unranked ones: neither can be owned
            var all = MstYoukai().Items.Where(x => x.MaxLevel > 0 && (int)x.YoukaiRarity > 0).Select(x => (long)x.YoukaiId).ToList();
            await GiveYokaiList(gdkey, all, max);
            return await DescribeAccount(gdkey);
        }

        private static TableParser<YwpMstYoukai> MstYoukai() =>
            new(DataManager.Logic.DataManager.GameDataManager.GetTableStringFromJson("ywp_mst_youkai"));

        //Adds every Yo-kai in the list that the account does not own yet. With max, owned ones are maxed too.
        private static async Task<int> GiveYokaiList(string gdkey, List<long> youkaiIds, bool max)
        {
            var mstYoukai = MstYoukai();
            var mstLevel = new TableParser<YwpMstYoukaiLevel>(DataManager.Logic.DataManager.GameDataManager.GetTableStringFromJson("ywp_mst_youkai_level"));
            var userYokai = new TableParser<YwpUserYoukai>(await UserData.GetYwpUserAsync<string>(gdkey, "ywp_user_youkai"));
            var userSkill = new TableParser<YwpUserYoukaiSkill>(await UserData.GetYwpUserAsync<string>(gdkey, "ywp_user_youkai_skill"));
            var userBonus = new TableParser<YwpUserYoukaiBonusEffect>(await UserData.GetYwpUserAsync<string>(gdkey, "ywp_user_youkai_bonus_effect"));
            var userDict = new TableParser.Logic.TableParser(await UserData.GetYwpUserAsync<string>(gdkey, "ywp_user_dictionary") ?? "");
            var userMission = new TableParser<YwpUserMission>(await UserData.GetYwpUserAsync<string>(gdkey, "ywp_user_mission"));
            int given = 0;
            foreach (var youkaiId in youkaiIds)
            {
                var mst = mstYoukai.Items.FirstOrDefault(x => x.YoukaiId == youkaiId);
                if (mst == null) continue;
                given++;
                bool owned = userYokai.Items.Any(x => x.YoukaiId == youkaiId);
                //AddYoukai on an owned Yo-kai only raises its Soultimate, which a plain "give" should not do
                if (!owned)
                {
                    await YoukaiManager.AddYoukai(userYokai, youkaiId, userSkill, userBonus, gdkey, userMission, true);
                    userDict = DictionaryManager.EditDictionary(userDict, youkaiId, true, true);
                }
                if (!max) continue;
                var mine = userYokai.Items.First(x => x.YoukaiId == youkaiId);
                var topLevel = mstLevel.Items.FirstOrDefault(x => x.LevelTtype == mst.LevelType && x.Level == mst.MaxLevel);
                mine.Level = mst.MaxLevel;
                mine.Hp = mst.MaxHp;
                mine.Atk = mst.MaxAtk;
                if (topLevel != null) mine.Exp = topLevel.BaseExp;
                mine.ExpDenominator = 0;
                mine.ExpNumerator = 0;
                mine.Percentage = 0;
                mine.IsLockedLevel = 0;
                var skill = userSkill.Items.FirstOrDefault(x => x.YoukaiId == youkaiId);
                if (skill != null)
                {
                    skill.Level = MAX_SOUL_LEVEL;
                    skill.Points = MAX_SOUL_POINTS;
                    skill.PercentageDenominator = 0;
                    skill.PercentageNumerator = 0;
                    skill.Percentage = 0;
                }
            }
            await UserData.SetYwpUserDictAsync(gdkey, new Dictionary<string, object?>
            {
                ["ywp_user_youkai"] = userYokai.ToString(),
                ["ywp_user_youkai_skill"] = userSkill.ToString(),
                ["ywp_user_youkai_bonus_effect"] = userBonus.ToString(),
                ["ywp_user_dictionary"] = userDict.ToString(),
                ["ywp_user_mission"] = userMission.ToString(),
            });
            return given;
        }

        private static async Task<object> GiveItem(JObject body)
        {
            var gdkey = Gdkey(body);
            await LoadUserData(gdkey);
            long itemId = (long)(body["itemId"] ?? throw new AdminException("No item chosen."));
            int count = (int)Math.Clamp((long?)body["count"] ?? 1, 1, 9999);
            var mstItem = new TableParser.Logic.TableParser(DataManager.Logic.DataManager.GameDataManager.GetTableStringFromJson("ywp_mst_item"));
            if (!mstItem.Table.Any(row => row[0] == itemId.ToString()))
                throw new AdminException($"Item {itemId} does not exist in the master data.");
            var userItem = new TableParser<YwpUserItem>(await UserData.GetYwpUserAsync<string>(gdkey, "ywp_user_item"));
            ItemManager.AddItem(userItem, itemId, count);
            await UserData.SetYwpUserAsync(gdkey, "ywp_user_item", userItem.ToString());
            return new { ok = true, itemId, count = userItem.Items.First(x => x.ItemId == itemId).Count };
        }

        private static object GetCatalog()
        {
            var gm = DataManager.Logic.DataManager.GameDataManager;
            var yokai = new TableParser.Logic.TableParser(gm.GetTableStringFromJson("ywp_mst_youkai")).Table
                .Where(row => row.Length > 7 && row[3] != "0" && row[7] != "0")
                .Select(row => new { id = row[0], name = row[1] });
            var items = new TableParser.Logic.TableParser(gm.GetTableStringFromJson("ywp_mst_item")).Table
                .Where(row => row.Length > 2)
                .Select(row => new { id = row[0], name = row[2] });
            return new { yokai, items };
        }
    }
}
