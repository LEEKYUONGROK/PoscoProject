using Assets.TutorialInfo.Scripts;
using Google.Protobuf;
using Google.Protobuf.Protocol;
using Google.Protobuf.WellKnownTypes;
using ServerCore;
using System;
using System.Collections;
using System.Collections.Generic;
using Unity.InferenceEngine;
using UnityEngine;


class PacketHandler
{
    //foreach (var element in ch_inpo.Inpo)
    public static void S_SensorsLog(PacketSession session, IMessage packet)
    {
        SensorsMsg SensorsData = packet as SensorsMsg;
        if (SensorsData == null)
            return;

        var SensorDic = AppManagers.OBJMananger.SensorDIC;
        foreach (SensorMsg SData in SensorsData.Info)
        {
            if(SensorDic.TryGetValue(SData.SensorID, out Sensor sensor))
            {
                if (sensor.Type == SensorType.Temperature)
                {
                    sensor.Function<string>(SData.Msg);
                }
                else if (SData.SensorID >= 300)
                {

                }
            }
   
        }
        //Managers.Network.Send(c_Sellect_Ch);
    }
    public static void GetSensorData(PacketSession session, IMessage packet)
    {
        SensorInpo sensorInpos = packet as SensorInpo;
        


    }
    public static void GetSensorDatas(PacketSession session, IMessage packet)
    {
        SensorInpos sensorInpos = packet as SensorInpos;
        foreach(var sensorinpo in sensorInpos.Info)
        {
            var AppOBJManager = AppManagers.OBJMananger;

            if (sensorinpo.ID < 300)
            {
                string[] result = sensorinpo.Topic.Split('/', StringSplitOptions.RemoveEmptyEntries);

                string FacNum = result[0].Replace(Default.Factory, "");
                string FloorNum = result[1].Replace("F", "");

                int FacNUM = 0; int FloorNUM = 0;
                if (int.TryParse(FacNum, out FacNUM) && 
                    int.TryParse(FloorNum, out FloorNUM))
                {
                    if (AppOBJManager.AppFactoryDic.TryGetValue(FacNUM, out AppFactory appFactory))
                    {

                        if (sensorinpo.Type == (int)SensorType.Temperature)
                        {
                            var TempSensor = appFactory.GetFloor(FloorNUM).Temp_Sensors;
                            if (TempSensor != null)
                            {
                                var sensor = AppOBJManager.SpawnPrefab
                                      (Prefabs.AppTempSensor.ToString(), TempSensor,
                                       new Vector3(sensorinpo.X, sensorinpo.Y, sensorinpo.Z),
                                       new Vector3(sensorinpo.Rotx, sensorinpo.Roty, sensorinpo.Rotz),
                                       sensorinpo.ID);

                                sensor.ID = sensorinpo.ID;
                                sensor.Topic = sensorinpo.Topic;
                                sensor.Type = (int)SensorType.Temperature;

                                AppOBJManager.SensorDIC.TryAdd(sensor.ID, sensor);
                            }
                        }
                        else if (sensorinpo.Type == (int)SensorType.Conveyor)
                        {
                            var Conveyors = appFactory.GetFloor(FloorNUM).Conveyors;
                            
                        }
                    }
                }
            }
            else
            {
                AppOBJManager.SensorDIC.TryAdd(sensorinpo.ID, new Sensor
                {
                    ID = sensorinpo.ID,
                    Topic = sensorinpo.Topic,
                    Type = (SensorType)sensorinpo.Type
                });
            }
        }
    }
}