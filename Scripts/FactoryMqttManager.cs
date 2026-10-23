using System;
using System.Collections.Generic;
using System.Globalization;
using System.Runtime.CompilerServices;
using System.Threading;
using System.Threading.Tasks;
using Assets.TutorialInfo.Scripts;
using MQTTnet;
using MQTTnet.Client;
using MQTTnet.Formatter;
using MQTTnet.Protocol;
using UnityEngine;
using UnityEngine.UI;


public class FactoryMqttManager : MonoBehaviour
{
    //"3.39.173.120"
    //127.0.0.1
    private string host = Default.BrokerIP;
    private int port = 1883;

    private IMqttClient _client;
    private MqttClientOptions _options;
    private CancellationTokenSource _cts;
    private Task _worker;

    private readonly object _lock = new object();
    // 센서별 최신 데이터만 보관
    private readonly Dictionary<int, Bundle> _latest = new Dictionary<int, Bundle>();
    // 전송 대기 중인 센서 ID
    private readonly Queue<int> _pending = new Queue<int>();

    public void Init()
    {
        _client = new MqttFactory().CreateMqttClient();

        _options = new MqttClientOptionsBuilder()
            .WithTcpServer(host, port)
            .WithClientId("unity-factory")
            .WithProtocolVersion(MqttProtocolVersion.V311)
            .Build();

        _cts = new CancellationTokenSource();
        _worker = Task.Run(() => SendLoopAsync(_cts.Token));
    }

    // 센서에서 호출하는 메서드
    public void EnqueueSensor(int id, Bundle mQSend)
    {
        lock (_lock)
        {
            if (!_latest.ContainsKey(id))
                _pending.Enqueue(id);

            _latest[id] = mQSend;
        }
    }

    private async Task SendLoopAsync(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (!_client.IsConnected)
                {
                    using (var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct))
                    {
                        //브로커와 연결이 끊어 지면 5초 대기
                        timeout.CancelAfter(TimeSpan.FromSeconds(5));
                        await _client.ConnectAsync(_options, timeout.Token);
                    }
                }

                int id = -1;
                Bundle value = null;

                lock (_lock)
                {
                    if (_pending.Count > 0)
                    {
                        id = _pending.Dequeue();
                        value = _latest[id];
                        _latest.Remove(id);
                    }
                }

                if (id < 0 || value == null)
                {
                    await Task.Delay(10, ct);
                    continue;
                }

                var message = new MqttApplicationMessageBuilder()
                    .WithTopic(value.topic)
                    .WithPayload(value.msg)
                    .WithQualityOfServiceLevel(MqttQualityOfServiceLevel.AtMostOnce)
                    .Build();

                try
                {
                    await _client.PublishAsync(message, ct);
                }
                catch
                {
                    // 아직 새로운 값이 없다면 기존 값 복원
                    lock (_lock)
                    {
                        if (!_latest.ContainsKey(id))
                        {
                            _latest[id] = value;
                            _pending.Enqueue(id);
                        }
                    }

                    throw;
                }
            }
            //무슨 예러인지 모르겠지만 멈추는 코드
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                break;
            }
            catch (Exception)
            {
                // 실패 시 재연결 간격
                try
                {
                    await Task.Delay(2000, ct);
                }
                catch (OperationCanceledException)
                {
                    break;
                }
            }
        }
    }

    private async void OnDestroy()
    {
        if (_cts == null)
            return;

        _cts.Cancel();

        try
        {
            if (_worker != null)
                await _worker;
        }
        catch (Exception) { }

        try
        {
            if (_client.IsConnected)
                await _client.DisconnectAsync();
        }
        catch (Exception) { }

        _client.Dispose();
        _cts.Dispose();
    }
}
