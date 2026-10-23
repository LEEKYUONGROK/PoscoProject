using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using static TMPro.TMP_Dropdown;

public class AppUIDropdow : MonoBehaviour
{
    private TMP_Dropdown dropdown;
    public int PreIndex { get; set; } = 0;

    public Action<int> CHValueAction { get; set; }
    public void Init()
    {
        dropdown = GetComponent<TMP_Dropdown>();
        dropdown.onValueChanged.AddListener(OnDropdownSelected);
    }
    public void ResetOption()
    {
        dropdown.ClearOptions();
    }

    public void AddOption(string option)
    {
        dropdown.options.Add(new OptionData(option));
    }

    public void SetOptions(List<string> options)
    {
        dropdown.AddOptions(options);
    }
    private void OnDropdownSelected(int index)
    {
        //string selectedText = dropdown.options[index].text;
        CHValueAction?.Invoke(index);
    }
}
