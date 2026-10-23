using ServerCore;
using System;
using System.Collections;
using System.Collections.Generic;
using System.Net;
using UnityEngine;
using Google.Protobuf;
using System.Net.Sockets;

public class NetworkManager
{
	ServerSession _session = null;

	public void Send(IMessage packet)
	{
		_session.Send(packet);
	}

	public void ServerDisconnected()
	{
        _session.Disconnect();
    }

	public void Init(string IP)
	{
        //DNS (Domain Name System)
        //string host = Dns.GetHostName();
        //"3.39.173.120"

        if (IPAddress.TryParse(IP, out IPAddress ipAddr))
        {
            Debug.Log($"IP 변환 성공: {ipAddr}");
            IPEndPoint endPoint = new IPEndPoint(ipAddr, 7777);

            Connector connector = new Connector();
            _session = new ServerSession();
            connector.Connect(endPoint, _session);

            AppManagers.UIManager.StartPannel.gameObject.SetActive(false);
            AppManagers.UIManager.SensorsPannel.gameObject.SetActive(true);
        }
        else
        {
            Debug.LogWarning("올바르지 않은 IP 주소");
        }
    }

    public void Update()
	{
		List<PacketMessage> list = PacketQueue.Instance.PopAll();
		foreach (PacketMessage packet in list)
		{
			Action<PacketSession, IMessage> handler = PacketManager.Instance.GetPacketHandler(packet.Id);
			if (handler != null)
				handler.Invoke(_session, packet.Message);
		}	
	}
}
