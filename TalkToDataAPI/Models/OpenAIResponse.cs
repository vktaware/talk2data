using System.Text.Json.Serialization;

namespace TalkToDataAPI.Models
{
    public class OpenAIResponse
    {
        [JsonPropertyName("choices")]
        public Choice[] Choices { get; set; }
    }

    public class Choice
    {
        [JsonPropertyName("message")]
        public OpenAIMessage Message { get; set; }
    }

    public class OpenAIMessage
    {
        [JsonPropertyName("content")]
        public string Content { get; set; }
    }
}
