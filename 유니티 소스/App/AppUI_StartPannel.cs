using GLTFast;
using NUnit.Framework;
using System;
using System.Collections.Generic;
using TMPro;
using Unity.VisualScripting;
using UnityEngine;

public class AppUI_StartPannel : MonoBehaviour
{
    public TextMeshProUGUI InputText { get; private set; }
    public ButtonScript ButtonScript { get; private set; }

    public void Init()
    {
        //주요 UI만 수동등록
        var InputTextTrans = FindChild("InputText");
        if (InputTextTrans != null)
        {
            InputText = InputTextTrans.GetComponent<TextMeshProUGUI>();
        }

        var ButtonScriptTrans = FindChild("ConnectBtn");
        if (ButtonScriptTrans != null)
        {
            ButtonScript = ButtonScriptTrans.GetComponent<ButtonScript>();
        }

        if (ButtonScript == null || InputText == null)
            Debug.LogWarning("UI 요소 참조 못함");


        ButtonScript.action = () =>
        {
            var ip = InputText.text.Replace("\u200B", "");
            AppManagers.Network.Init(ip);
        };
    }

    public Transform FindChild(string targetName)
    {
        foreach (Transform child in GetComponentsInChildren<Transform>(true))
        {
            if (child == transform)
                continue;

            if (child.name == targetName)
                return child;
        }
        return null;
    }
}
