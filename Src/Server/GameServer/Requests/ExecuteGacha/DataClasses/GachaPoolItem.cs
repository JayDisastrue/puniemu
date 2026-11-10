using Newtonsoft.Json;
using Puniemu.Src.Server.GameServer.DataClasses;

namespace Puniemu.Src.Server.GameServer.Requests.ExecuteGacha.DataClasses
{
    public class GachaPoolItem
    {
        [JsonProperty("gachaId")]
        public int GachaId { get; set; }

        [JsonProperty("convertItem")]
        public Dictionary<string, ItemWonPopup> ConvertItem { get; set; }

        [JsonProperty("weights")]
        public Dictionary<string, double> Weights { get; set; }

        [JsonProperty("youkai")]
        public Dictionary<string, List<long>> Yokais { get; set; }

        [JsonProperty("items")]
        public Dictionary<string, List<long>> Items { get; set; }

        //Optional: rank shown for prizes from an item pool (pool key -> rank number). Sets the capsule colour too.
        [JsonProperty("itemRanks")]
        public Dictionary<string, int>? ItemRanks { get; set; }
        [JsonProperty("rateUp")]
        public Dictionary<long, double>? RateUp { get; set; }
    }
}
