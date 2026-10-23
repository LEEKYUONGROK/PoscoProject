using Assets.TutorialInfo.Scripts;
using Google.Protobuf.Protocol;
using System.Collections.Generic;
using Unity.InferenceEngine;
using UnityEngine;
using UnityEngine.InputSystem;

public class AppObjManager
{
    Dictionary<string, GameObject> prefabDict = new Dictionary<string, GameObject>(); 

    public Dictionary<int,Sensor> SensorDIC { get { return SensorDictionary; } }
    Dictionary<int ,Sensor> SensorDictionary = new Dictionary<int ,Sensor>();

    //public Dictionary<int, Sensor> RealSensorDIC { get { return _RealSensorDIC; } }
    //Dictionary<int, Sensor> _RealSensorDIC = new Dictionary<int, Sensor>();

    public Dictionary <int , AppFactory> AppFactoryDic { get { return AppFactoryDictionary; } }
    Dictionary<int, AppFactory> AppFactoryDictionary = new Dictionary<int, AppFactory>();

    public void Init()
    {
        LoadPrefabsDic();

        Transform Factorys =
            GameObject.Find(nameof(OBJNames.Factorys)).transform;

        if (Factorys == null)
        {
            Debug.LogError("참조할 공장이 없음");
            return;
        }

        for (int i = 0; i < Factorys.childCount; i++)
        {
            var AppFactory 
                = Factorys.GetChild(i).GetComponent<AppFactory>();

            AppFactory.Init(i);
            AppFactoryDictionary.TryAdd(i, AppFactory);
        }
    }
    public void LoadPrefabsDic()
    {
        GameObject[] loadedPrefabs = Resources.LoadAll<GameObject>("Prefabs");
        foreach (GameObject prefab in loadedPrefabs)
        {
            prefabDict.TryAdd(prefab.name, prefab);
        }
    }
    
    public GameObject GetPrefab(string prefabName)
    {
        if (prefabDict.TryGetValue(prefabName, out GameObject prefab))
        {
            return prefab;
        }
        return null;
    }

    //SensorINPO 리스트를 받으면 값 호출 실체화
    public Sensor SpawnPrefab(string resourcePrefabName,Transform targetParent,
                Vector3 spawnPosition,Vector3 spawnRotationEuler,int ID)
    {

        GameObject prefab = GetPrefab(resourcePrefabName);
        if (prefab == null)
        {
            Debug.LogError("prefab X");
            return null;
        }

        Transform InstTrans = Object.Instantiate(prefab, targetParent, false).transform;
        Quaternion rotation = Quaternion.Euler(spawnRotationEuler);

        InstTrans.localPosition = spawnPosition;
        InstTrans.localRotation = rotation;

        return InstTrans.transform.GetComponent<Sensor>();
    }
}
