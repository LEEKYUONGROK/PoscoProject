using Google.Protobuf.Protocol;
using System;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;

public class ButtonScript : MonoBehaviour, IPointerClickHandler
{
    public Action action { get; set; }


    public void OnPointerClick(PointerEventData eventData)
    {
        if (action != null)
            action?.Invoke();
    }
}