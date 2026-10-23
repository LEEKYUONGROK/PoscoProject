using System.Collections;
using System.Collections.Generic;
using System.Xml.Serialization;
using TMPro;
using Unity.VisualScripting;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.UIElements;

public class AppManagers : MonoBehaviour
{
    static public AppManagers Instance { get { return s_instance; } }
    static AppManagers s_instance;

    public static NetworkManager Network { get { return Instance._network; } }
    NetworkManager _network = new NetworkManager();

    public static AppObjManager OBJMananger { get { return Instance._OBJMananger; } }
    AppObjManager _OBJMananger = new AppObjManager();

    public static AppUIManager UIManager { get { return Instance._UIManager; } }
    AppUIManager _UIManager = new AppUIManager();

    void Update()
    {
        _network.Update();
    }

    private void Start()
    {
        Initialization();
    }

    public void Initialization()
    {
        if (s_instance == null)
        {
            s_instance = this;
            DontDestroyOnLoad(this);
            //Network.Init();
            OBJMananger.Init();
            UIManager.Init();
        }
    }


    public static void QuitGame()
    {
        #if UNITY_EDITOR
                UnityEditor.EditorApplication.isPlaying = false;
        #else
                    Application.Quit();
        #endif
    }

}
