using Assets.TutorialInfo.Scripts;
using TMPro;
using UnityEngine;

public class AppTempSensor : Sensor
{
    [SerializeField]
    private TextMeshPro DisplayText;

    public override void Function<T>(T value) 
    {
        DisplayText.text =
            $"ID - {ID}\n{ value.ToString() }";
    }
}