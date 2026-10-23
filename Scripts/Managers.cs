using UnityEngine;


public class Managers : MonoBehaviour
{
    public static FactoryMqttManager MqttManager = new FactoryMqttManager();
    public static ObjManager OBJManager = new ObjManager();

    public static WeatherManager WeatherManager { get; private set; }
    void Start()
    {
        Application.runInBackground = true;
        // 창 모드로 변경 (1280 × 720)
        Screen.SetResolution(1280, 720, FullScreenMode.Windowed);
        WeatherManager = transform.GetComponent<WeatherManager>();

        MqttManager.Init();
        OBJManager.Init();
    }
}
