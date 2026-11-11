using Newtonsoft.Json;
using Puniemu.Src.Server.GameServer.DataClasses;
using Puniemu.Src.Utils.GeneralUtils;
using System.Xml.Linq;
namespace Puniemu.Src.Server.GameServer.Requests.UserInfoRefresh.DataClasses
{
    public class UserInfoRefreshResponse : CommonResponse
    {

        // Basic user data.
        [JsonProperty("ywp_user_data")]
        public YwpUserData UserData { get; set; }

        public UserInfoRefreshResponse(YwpUserData userData)
        {
            ResultCode = 0;
            NextScreenType = 0;
            UserData = userData;
            ResultType = 0;
        }
        public Dictionary<string, object> ToDictionary()
        {
            //Serialize through the JSON names so the keys match what the game expects
            //(resultCode, serverDt, ...) instead of the C# property names.
            var dict = Newtonsoft.Json.Linq.JObject.FromObject(this).ToObject<Dictionary<string, object>>()!;

            return dict;
        }
    }
}
