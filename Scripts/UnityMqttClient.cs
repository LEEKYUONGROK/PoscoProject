using System;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Concurrent;
using UnityEngine;
using MQTTnet;
using MQTTnet.Client;
using TMPro;
using Assets.TutorialInfo.Scripts;
using System.Collections.Generic;


#if UNITY_EDITOR
using UnityEditor;
#endif

public class UnityMqttClient : MonoBehaviour
{
    private IMqttClient mqttClient;
    private MqttClientOptions options;
    private readonly CancellationTokenSource lifetimeCts = new CancellationTokenSource();
    private Task startupTask;
    private Task shutdownTask;
    private bool isShuttingDown;
    private bool quitAllowed;
    private bool quitShutdownStarted;

    //3.39.173.120
    //"127.0.0.1"
    private string brokerAddress = Default.BrokerIP;
    private int port = 1883;
    string myTopic = "factory/receive"; // #은 와일드카드(해당 경로 하위 모든 토픽 수신)

    // 메인 스레드 처리를 위한 큐 (이번엔 토픽과 페이로드를 함께 저장)
    private ConcurrentQueue<string> messageQueue = new ConcurrentQueue<string>();

    private void Awake()
    {
        Application.wantsToQuit += OnWantsToQuit;
#if UNITY_EDITOR
        EditorApplication.playModeStateChanged += OnPlayModeChanged;
#endif
    }

    private void Start()
    {
        
        var factory = new MqttFactory();
        mqttClient = factory.CreateMqttClient();

        options = new MqttClientOptionsBuilder()
            .WithTcpServer(brokerAddress, port)
            .WithClientId("FactoryClient")
            .Build();

        mqttClient.ApplicationMessageReceivedAsync += e =>
        {
            string payload = Encoding.UTF8.GetString(e.ApplicationMessage.PayloadSegment);
            messageQueue.Enqueue(payload);
            return Task.CompletedTask;
        };
        mqttClient.DisconnectedAsync += OnDisconnectedAsync;
        startupTask = ConnectAndSubscribeAsync();
    }

    private async Task ConnectAndSubscribeAsync()
    {
        try
        {
            await mqttClient.ConnectAsync(options, lifetimeCts.Token);
            if (isShuttingDown)
                return;

            await mqttClient.SubscribeAsync(myTopic, cancellationToken: lifetimeCts.Token);
            Debug.Log("MQTT 최초 연결 성공!");
        }
        catch (OperationCanceledException) when (lifetimeCts.IsCancellationRequested)
        {
            // 정상 종료 과정에서 연결 작업이 취소된 경우입니다.
        }
        catch (Exception ex)
        {
            Debug.LogError($"최초 연결 실패: {ex.Message}");
        }
    }

    private async Task OnDisconnectedAsync(MqttClientDisconnectedEventArgs e)
    {
        if (isShuttingDown || lifetimeCts.IsCancellationRequested)
            return;

        Debug.LogWarning("MQTT 브로커와 연결이 끊어졌습니다. 3초 후 재접속을 시도합니다...");
        try
        {
            await Task.Delay(TimeSpan.FromSeconds(3), lifetimeCts.Token);
            if (isShuttingDown)
                return;

            await mqttClient.ConnectAsync(options, lifetimeCts.Token);
            await mqttClient.SubscribeAsync(myTopic, cancellationToken: lifetimeCts.Token);
            Debug.Log("MQTT 재접속 및 토픽 재구독 완료!");
        }
        catch (OperationCanceledException) when (lifetimeCts.IsCancellationRequested)
        {
            // 종료 시 취소된 재연결은 다시 시작하지 않습니다.
        }
        catch (Exception ex)
        {
            if (!isShuttingDown)
                Debug.LogError($"재접속 실패: {ex.Message}");
        }
    }

    private bool OnWantsToQuit()
    {
        if (quitAllowed)
            return true;

        // wantsToQuit는 false를 반환해야 비동기 MQTT 정리 완료 후 종료를 재요청할 수 있습니다.
        if (!quitShutdownStarted)
        {
            quitShutdownStarted = true;
            ShutdownAndQuitAsync();
        }
        return false;
    }

    private async void ShutdownAndQuitAsync()
    {
        await BeginShutdownAsync();
        quitAllowed = true;
        Application.Quit();
    }

#if UNITY_EDITOR
    private void OnPlayModeChanged(PlayModeStateChange state)
    {
        if (state == PlayModeStateChange.ExitingPlayMode)
        {
            // Unity의 Play 모드 변경 이벤트는 종료를 보류할 수 없어 취소와 연결 해제는 best effort입니다.
            _ = BeginShutdownAsync();
        }
    }
#endif

    void Update()
    {
        var sensorDic = Managers.OBJManager.DicTotalSensors;
        // 5. 수신 데이터 처리 (메인 스레드)
        while (messageQueue.TryDequeue(out string payload))
        {
            string[] result = payload.Split('|', StringSplitOptions.RemoveEmptyEntries);

            int Command = 0; Sensor sensor = null;
            if (result.Length == 3 &&
               sensorDic.TryGetValue(int.Parse(result[0]), out sensor) ||
               int.TryParse(result[2], out Command))
            {
                if (Command == 1)
                    sensor.SwitchON = true;
                else
                    sensor.SwitchON = false;
            }
        }
    }

    private Task BeginShutdownAsync()
    {
        if (shutdownTask != null)
            return shutdownTask;

        isShuttingDown = true;
        lifetimeCts.Cancel();
        if (mqttClient != null)
            mqttClient.DisconnectedAsync -= OnDisconnectedAsync;

        shutdownTask = ShutdownAsync();
        return shutdownTask;
    }

    private async Task ShutdownAsync()
    {
        try
        {
            // 진행 중인 최초 연결도 끝나도록 기다린 뒤 연결 해제를 수행합니다.
            if (startupTask != null)
                await startupTask;

            if (mqttClient != null && mqttClient.IsConnected)
            {
                using (var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(5)))
                {
                    await mqttClient.DisconnectAsync(cancellationToken: timeout.Token);
                }
            }
        }
        catch (OperationCanceledException)
        {
            // 5초 내 브로커 응답이 없으면 앱 종료가 무기한 대기하지 않도록 정리를 중단합니다.
            Debug.LogWarning("MQTT 연결 해제가 시간 초과 또는 종료 취소로 중단되었습니다.");
        }
        catch (Exception ex)
        {
            Debug.LogError($"MQTT 종료 처리 실패: {ex.Message}");
        }
        finally
        {
            if (mqttClient != null)
            {
                mqttClient.Dispose();
                mqttClient = null;
            }

            lifetimeCts.Dispose();
        }
    }

    private void OnDestroy()
    {
        Application.wantsToQuit -= OnWantsToQuit;
#if UNITY_EDITOR
        EditorApplication.playModeStateChanged -= OnPlayModeChanged;
#endif

        // 강제 종료나 씬에서 제거되는 경우에도 취소를 먼저 요청합니다.
        // OS의 강제 종료/프로세스 강제 종료는 Unity 콜백을 보장하지 않으므로 graceful 종료를 보장할 수 없습니다.
        _ = BeginShutdownAsync();
    }
}