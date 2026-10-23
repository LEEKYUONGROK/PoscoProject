using Assets.TutorialInfo.Scripts;
using System;
using System.Collections.Generic;
using Unity.VisualScripting;
using UnityEngine;


public class AppUIManager : MonoBehaviour
{
    public Canvas canvas { get; private set; }
    public AppUI_StartPannel StartPannel { get; private set; }
    public AppUI_SensorsPannel SensorsPannel { get; private set; }

    public void Init()
    {
        canvas = GameObject.Find("Canvas").GetComponent<Canvas>();
        StartPannel = canvas.transform.Find("AppUI_StartPannel")
                      .GetComponent<AppUI_StartPannel>();

        SensorsPannel = canvas.transform.Find("AppUI_SensorsPannel")
                      .GetComponent<AppUI_SensorsPannel>();

        StartPannel.Init();
        SensorsPannel.Init();

        StartPannel.gameObject.SetActive(true);
        SensorsPannel.gameObject.SetActive(false);
    }
}