using Assets.TutorialInfo.Scripts;
using System.Collections.Generic;
using UnityEngine;

public class ObjManager
{
    public int GetID { get { return IDCount++; } }
    private int IDCount = 0;

    public Dictionary<int, Sensor> DicTotalSensors { get { return _dicTotalSensors; } }
    private Dictionary<int,Sensor> _dicTotalSensors = new Dictionary<int,Sensor>();

    public bool GetSensorTopic(int key,ref string topic)
    {
        Sensor sensor = null;
        if (_dicTotalSensors.TryGetValue(key, out sensor))
        {
            topic = sensor.Topic;
            return true;
        }
        return false;
    }
    public void Init()
    {
        Transform Factorys = 
            GameObject.Find(nameof(OBJNames.Factorys)).transform;

        if (Factorys == null)
        {
            Debug.LogError("참조할 공장이 없음");
            return;
        }

        for (int i = 0; i < Factorys.childCount; i++)
        {
            var FactoryRegist = 
                Factorys.GetChild(i).GetComponent<FactoryDataResister>();
            
            if (FactoryRegist == null)
            {
                Debug.LogWarning("Factory Component null");
                continue;
            }

            FactoryRegist.Init(i);
            FactoryRegist.GetSensorData(ref _dicTotalSensors, ref IDCount);
        }
    }
}