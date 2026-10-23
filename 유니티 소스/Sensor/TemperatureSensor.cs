using Assets.TutorialInfo.Scripts;
using System;
using TMPro;
using Unity.VisualScripting;
using UnityEngine;


public class TemperatureSensor : Sensor
{

    [SerializeField]
    private TextMeshPro DisplayText;

    private float Temp = 0;
    public float Temperature
    {
        get { return Temp; }
        set 
        { 
            Temp = value;
            Refresh();
        }
    }
    private float Humidity = 0;
    public float Humid
    {
        get { return Humidity; }
        set { Humidity = value; }
    }
    public override bool SwitchON 
    {
        get { return base.SwitchON; }

        set
        {
            base.SwitchON = value;
            if (!base.SwitchON)
            {
                NoneDisplay();
            }
        }
    }
    private void UpdateSensor()
    {
        if(SwitchON)
        {
            var ran = UnityEngine.Random.Range(-2.5f, 1.5f);

            Humidity =
                Mathf.Round(Managers.WeatherManager.Humidity + (ran * 10f) / 10f);
            Humidity = Mathf.Clamp(Humidity, 0f, 100f);

            Temperature = 
                Mathf.Round(Managers.WeatherManager.Temperature + (ran * 10f) / 10f);

            MakePlayload();
        }
    }

    public override void Init
        (int ID, int FactoryNum, int FloorNum, SensorType type = SensorType.Temperature)
    {
        base.Init(ID, FactoryNum, FloorNum, type);
        InvokeRepeating(nameof(UpdateSensor), 1f, 3f);
    }
    public override void MakePlayload()
    {
        //원본
        //message = f"{SensorID}/{ temp }/{ str_dt }"
        string msg = 
            $@"{{""Temp"": {Managers.WeatherManager.Temperature},""Humidity"": {Managers.WeatherManager.Humidity}}}";

        Managers.MqttManager.EnqueueSensor
            (ID, new Bundle(Topic, $"{msg}|{Default.NowTime()}"));
    }

    void NoneDisplay()
    {
        DisplayText.text = "";
    }
    void Refresh()
    {
        DisplayText.text
        = $"ID - {ID}\n{ Default.TempText}{ Temperature } / { Default.HumidText }{Humid}";
    }

    private void OnDisable()
    {
        CancelInvoke(nameof(UpdateSensor));
    }
}
