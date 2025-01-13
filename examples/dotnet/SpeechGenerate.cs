

using System.Text.Json;
using RestSharp;

var apiKey = "your api key";

var client = new RestClient("https://api.murf.ai");
var request = new RestRequest("/v1/speech/generate", Method.Post);
request.AddHeader("Content-Type", "application/json");
request.AddHeader("Accept", "application/json");
request.AddHeader("api-key", apiKey);

var body = new
{
    voiceId                 = "en-US-natalie",
    style                   = "Promo",
    text                    = "In this experiential e-learning module, you’ll master the basics of using this Text to Speech widget",
    rate                    = 0,
    pitch                   = 0,
    sampleRate              = 48000,
    format                  = "MP3",
    channelType             = "MONO",
    pronunciationDictionary = new {},
    encodeAsBase64          = false,
    variation               = 1,
    audioDuration           = 0,
    modelVersion            = "GEN2",
    multiNativeLocale       = "en-US"
};

request.AddParameter("application/json", body, ParameterType.RequestBody);
var response = client.Execute(request);

if (response.IsSuccessful)
{
    using JsonDocument doc = JsonDocument.Parse(response.Content);
    JsonElement root = doc.RootElement;

    if (root.TryGetProperty("audioFile", out JsonElement audioFileElement))
    {
        var audioUrl        = audioFileElement.GetString();
        var downloadClient  = new RestClient(audioUrl);
        var downloadRequest = new RestRequest("", Method.Get);

        response = await downloadClient.ExecuteAsync(downloadRequest);

        if (response.IsSuccessStatusCode)
        {
            File.WriteAllBytes(@"C:\src\sample.mp3", response.RawBytes);

        }
    }
}

