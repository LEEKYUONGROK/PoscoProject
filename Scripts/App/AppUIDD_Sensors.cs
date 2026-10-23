using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using static TMPro.TMP_Dropdown;

public class AppUIDD_Sensors : MonoBehaviour
{
    private TMP_Dropdown dropdown;

    public List<string> VirOption { get; set; } = new List<string>();
    public List<string> RealOption { get; set; } = new List<string>();

    public int SelectIndex { get; set; }
    public bool IsVirtual_Now { get; set; } = true;
    //public Action<int> CHValueAction { get; set; }
    public void Init()
    {
        dropdown = GetComponent<TMP_Dropdown>();
        dropdown.onValueChanged.AddListener(OnDropdownSelected);
    }

    public void ResetOption()
    {
        dropdown.ClearOptions();
    }

    public void SelectOption(bool ISVirtual)
    {
        if(ISVirtual) 
        { 
            dropdown.AddOptions(VirOption);
            IsVirtual_Now = true;
        }
        else 
        { 
            dropdown.AddOptions(RealOption);
            IsVirtual_Now = false;
        }
        dropdown.RefreshShownValue();
    }

    public void AddOption(string option, bool Select_Vir)
    {
        //&& IsVirtual_Now == true
        //dropdown.options.Add(new OptionData(option))
        if (Select_Vir == true)
        {
            VirOption.Add(option);
            if (IsVirtual_Now == true)
            {
                dropdown.options.Add(new OptionData(option));
                dropdown.RefreshShownValue();
            }
        }
        else //Select_Vir == false
        {
            RealOption.Add(option);
            if (IsVirtual_Now == false)
            {
                dropdown.options.Add(new OptionData(option));
                dropdown.RefreshShownValue();
            }
        }
    }
    private void OnDropdownSelected(int index)
    {
        //string selectedText = dropdown.options[index].text;
        //CHValueAction?.Invoke(index);
        SelectIndex = index;
    }
}
