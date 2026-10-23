using Assets.TutorialInfo.Scripts;
using System.Collections.Generic;
using System.Xml.Serialization;
using UnityEngine;

public class Floor
{
    public int Num { get; set; } //0층 부터 시작
    public Transform transform { get; set; }
    public Transform Temp_Sensors { get; set; }
    public Transform Conveyors { get; set; }
}
public class FactoryDataResister : MonoBehaviour
{
    public int FactoryNum { get; private set; }
    public Floor[] FloorArr { get; private set; }

    public Floor GetFloor(int num)
    {
        if (num < 0 || num >= FloorArr.Length)
            return null;

        return FloorArr[num];
    }
    public void Init(int factory_num)
    {
        FactoryNum = factory_num;
        FloorArr = new Floor[transform.childCount];

        for (int i = 0; i < transform.childCount; i++)
        {
            FloorArr[i] = new Floor();
            FloorArr[i].Num = i;
            FloorArr[i].transform = transform.GetChild(i);
        }
    }

    public void GetSensorData(ref Dictionary<int,Sensor> dicSensor, ref int IDCount)
    {
        foreach (var Floor in FloorArr)
        {
            Floor.Temp_Sensors = Floor.transform.Find(nameof(OBJNames.Temp_Sensors));
            if (Floor.Temp_Sensors != null)
            {
                for (int i = 0; i < Floor.Temp_Sensors.childCount; i++)
                {
                    var TempSensor = Floor.Temp_Sensors.GetChild(i).GetComponent<TemperatureSensor>();
                    if (TempSensor == null)
                    {
                        continue;
                    }

                    TempSensor.Init(IDCount, FactoryNum, Floor.Num);
                    dicSensor.Add(IDCount++, TempSensor);
                    TempSensor.RegistDeviceMsg();
                }
            }

            //컨베이어 등록
/*            Floor.Conveyors = transform.Find(nameof(OBJNames.Conveyors));
            if (Floor.Conveyors != null)
            {
                for (int i = 0; i < Floor.Conveyors.childCount; i++)
                {
                    var Conveyors = Floor.Conveyors.GetChild(i).GetComponent<TemperatureSensor>();
                    if (Conveyors == null)
                    {
                        continue;
                    }

                    Conveyors.Init(IDCount, FactoryNum, Floor.Num);
                    dicSensor.Add(IDCount++, Conveyors);
                    Conveyors.RegistDeviceMsg();
                }
            }*/
        }
    }
}
