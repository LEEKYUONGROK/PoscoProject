using Assets.TutorialInfo.Scripts;
using Google.Protobuf.Protocol;
using Google.Protobuf.WellKnownTypes;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

public class AppUI_SensorsPannel : MonoBehaviour
{
    public AppUIDropdow DD_ISVirtual { get; private set; }
    public AppUIDD_Sensors DD_SensorsID { get; private set; }
    public ButtonScript ReferenceBtn { get; private set; }
    public void Init()
    {
        DD_ISVirtual = transform.GetChild(0).GetComponent<AppUIDropdow>();
        DD_SensorsID = transform.GetChild(1).GetComponent<AppUIDD_Sensors>();
        ReferenceBtn = transform.GetChild(2).GetComponent<ButtonScript>();

        if (DD_ISVirtual == null || 
            DD_SensorsID == null || ReferenceBtn == null)
        {
            Debug.LogError("검색 UI 참조 실패");
        }

        DD_ISVirtual.Init();
        DD_SensorsID.Init();
        //DD_SensorsID.ResetOption();

        DD_ISVirtual.CHValueAction = (CurrntValue) => 
        {
            var SensorDic = AppManagers.OBJMananger.SensorDIC;
            if (SensorDic.Count == 0)
                return;

            if (CurrntValue != DD_ISVirtual.PreIndex)
                DD_SensorsID.ResetOption();

            //value가 1이면 버추얼 2이면 리얼
            if (CurrntValue == 1)
            {
                if (DD_SensorsID.VirOption.Count == 0)
                {
                    List<string> opttion = new List<string>();
                    for (int i = 0; i <= 50; i++)
                    {
                        if(SensorDic.TryGetValue(i, out Sensor TMP))
                            opttion.Add(TMP.ID.ToString());
                    }

                    DD_SensorsID.VirOption = opttion;
                }
                DD_SensorsID.SelectOption(true);
            }
            else if(CurrntValue == 2)
            {
                if (DD_SensorsID.RealOption.Count == 0)
                {
                    List<string> opttion = new List<string>();

                    for (int i = Default.StartRealID; i <= SensorDic.Keys.Max(); i++)
                    {
                        if (SensorDic.TryGetValue(i, out Sensor TMP))
                            opttion.Add(TMP.ID.ToString());
                    }

                    DD_SensorsID.RealOption = opttion;
                }
                DD_SensorsID.SelectOption(false);
            }

            DD_ISVirtual.PreIndex = CurrntValue;
        };
        
        ReferenceBtn.action = () => 
        {
            var OBJDic = AppManagers.OBJMananger.SensorDIC;
            if (OBJDic.TryGetValue(DD_SensorsID.SelectIndex, out Sensor sensor))
            {
                if (DD_SensorsID.SelectIndex < Default.StartRealID)
                    sensor.SendMsgToBack(DD_SensorsID.SelectIndex, 1, true);
                else
                    sensor.SendMsgToBack(DD_SensorsID.SelectIndex, 1, false);
            }
        };
    }
}