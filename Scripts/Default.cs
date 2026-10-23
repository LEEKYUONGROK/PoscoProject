using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace Assets.TutorialInfo.Scripts
{

    public class Bundle
    {
        public Bundle(string topic,string msg) 
        { this.topic = topic; this.msg = msg; }
        public string topic { get; set; }
        public string msg { get; set; }
    }

    internal class Default
    {
        public const int StartRealID = 301;
        public const int VirtualValue = 1;
        public const string TempText = "Temp : ";
        public const string HumidText = "Humid : ";
        public const string Factory = "Factory";
        public const string Floor = "F";

        //3.39.173.120
        //"127.0.0.1"
        public const string BrokerIP = "3.39.173.120";
        public const string RegistTopic = "factory/register";

        const string yyHHmmss = "yyyy-MM-dd HH:mm:ss";
        public static string NowTime()
        {
            return DateTime.Now.ToString(yyHHmmss);
        }
    }

    //센서 오브젝트 이름
    public enum OBJNames
    {
        Factorys = 0,
        Temp_Sensors = 1,
        Camera = 2,
        Conveyors = 3,
    }

    public enum Prefabs
    {
        AppTempSensor = 0,
        Conveyor = 1,
        Display = 2,
        F = 3,
        TempSensor = 4,
    }

    public enum SensorType
    {
        Temperature = 0,
        Conveyor = 1,
        Camera = 2,
        FireSensors = 3,
    }
}
