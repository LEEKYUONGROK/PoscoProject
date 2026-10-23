
using System;
using System.Collections;
using Unity.VisualScripting;
using UnityEngine;
using UnityEngine.Networking;

public class WeatherManager : MonoBehaviour
{
    public float Temperature { get; private set; }
    public float Humidity { get; private set; }

    // 경상북도 포항시
    private const string URL =
        "https://api.open-meteo.com/v1/forecast" +
        "?latitude=36.0190&longitude=129.3435" +
        "&current=temperature_2m,relative_humidity_2m";

    [System.Serializable]
    public class WeatherResponse
    {
        public WeatherCurrent current;
    }

    [System.Serializable]
    public class WeatherCurrent
    {
        public float temperature_2m;
        public float relative_humidity_2m;
    }
    private void Start()
    {
        StartCoroutine(UpdateWeather());
    }

    private IEnumerator UpdateWeather()
    {
        while (true)
        {
            yield return StartCoroutine(GetWeather());
            yield return new WaitForSeconds(10f);
        }
    }

    public IEnumerator GetWeather()
    {
        using (UnityWebRequest request = UnityWebRequest.Get(URL))
        {
            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                Debug.LogError(request.error);
                yield break;
            }
            string json = request.downloadHandler.text;

            WeatherResponse data =
                JsonUtility.FromJson<WeatherResponse>(json);

            if (data == null)
            {
                Debug.LogError("WeatherResponse 객체가 null");
                yield break;
            }

            if (data.current == null)
            {
                Debug.LogError("current 필드가 null");
                yield break;
            }

            Temperature = data.current.temperature_2m;
            Humidity = data.current.relative_humidity_2m;

            Debug.Log($"온도: {Temperature}°C, 습도: {Humidity}%");
        }
    }
}
