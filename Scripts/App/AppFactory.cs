using Assets.TutorialInfo.Scripts;
using NUnit.Framework;
using UnityEngine;

public class AppFactory : MonoBehaviour
{
    public int FactoryNum { get; set; }
    public Floor[] FloorArr = null;

    public void Init(int FactNum)
    {
        FactoryNum = FactNum;
        FloorArr = new Floor[transform.childCount];

        for (int i = 0; i < transform.childCount; i++)
        {
            FloorArr[i] = new Floor();
            FloorArr[i].Num = i + 1;
            FloorArr[i].transform = transform.GetChild(i);
        }
        foreach (Floor floor in FloorArr) 
        {
            floor.Temp_Sensors = floor.transform.Find(nameof(OBJNames.Temp_Sensors));
            floor.Conveyors = floor.transform.Find(nameof(OBJNames.Conveyors));
        }
    }

    public Floor GetFloor(int index)
    {
        if (index < 0 || index >= FloorArr.Length)
            return null;

        return FloorArr[index];
    }
}