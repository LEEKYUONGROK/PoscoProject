using Assets.TutorialInfo.Scripts;
using Google.Protobuf.Protocol;
using UnityEngine;
using UnityEngine.InputSystem;

public class Sensor : MonoBehaviour
{
    public int ID { get; set; }
    public string Topic { get; set; }
    public SensorType Type { get; set; }

    private bool _SwitchON = true;
    public virtual bool SwitchON 
    { get { return _SwitchON; } set { _SwitchON = value; } }
    public virtual void MakePlayload() { }


    //app에서 작동정의
    public virtual void Function<T>(T value) { }

    public virtual void Init
        (int ID,int FactoryNum,int FloorNum,SensorType type) 
    {
        this.ID = ID;
        Type = type; SwitchON = true;
        Topic = $"Factory{FactoryNum}/F{FloorNum}/{ID}";
    }


    //App센서에서만 사용
    public void SendMsgToBack(int SensorID,int CommandID,bool ToVirFactory)
    {
        ClientCommand msg = new ClientCommand();
        msg.SensorID = SensorID;
        msg.CommandId = CommandID;
        msg.ToTopic = Topic;
        msg.ToFactory = ToVirFactory;
        AppManagers.Network.Send(msg);
    }

    //토픽 등록 메시지 전송
    public void RegistDeviceMsg()
    {
        var pos = transform.position;
        var rotat = transform.eulerAngles;

        var MsgBundle = new Bundle(Default.RegistTopic,
            $"{ID}|{(int)Type}|{Topic}|{pos.x}|{pos.y}|{pos.z}|{rotat.x}|{rotat.y}|{rotat.z}|{Default.VirtualValue}");

        Managers.MqttManager.EnqueueSensor(ID, MsgBundle);
    }
}