using Google.Protobuf;
using Google.Protobuf.Protocol;
using ServerCore;
using System;
using System.Collections.Generic;

class PacketManager
{
	static PacketManager _instance = new PacketManager();
	public static PacketManager Instance { get { return _instance; } }

	PacketManager()
	{
		Register();
	}

	Dictionary<ushort, Action<PacketSession, ArraySegment<byte>, ushort>> _onRecv 
		= new Dictionary<ushort, Action<PacketSession, ArraySegment<byte>, ushort>>();
	
	Dictionary<ushort, Action<PacketSession, IMessage>> _handler 
		= new Dictionary<ushort, Action<PacketSession, IMessage>>();

    public void CustomHandler(PacketSession session, IMessage buffer, ushort id)
    {
        PacketQueue.Instance.Push(id, buffer);
    }

	public void Register()
	{
        _onRecv.Add((ushort)MsgId.SensorsMsg, MakePacket<SensorsMsg>);
        _handler.Add((ushort)MsgId.SensorsMsg, PacketHandler.S_SensorsLog);

		_onRecv.Add((ushort)MsgId.SensorInpos, MakePacket<SensorInpos>);
		_handler.Add((ushort)MsgId.SensorInpos, PacketHandler.GetSensorDatas);

        _onRecv.Add((ushort)MsgId.SensorInpo, MakePacket<SensorInpo>);
        _handler.Add((ushort)MsgId.SensorInpo, PacketHandler.GetSensorData);
    }

    public void OnRecvPacket(PacketSession session, ArraySegment<byte> buffer)
	{
		ushort count = 0;

		ushort size = BitConverter.ToUInt16(buffer.Array, buffer.Offset);
		count += 2;
		ushort id = BitConverter.ToUInt16(buffer.Array, buffer.Offset + count);
		count += 2;

		Action<PacketSession, ArraySegment<byte>, ushort> action = null;
		if (_onRecv.TryGetValue(id, out action))
			action.Invoke(session, buffer, id);
	}

	void MakePacket<T>(PacketSession session, ArraySegment<byte> buffer, ushort id) where T : IMessage, new()
	{
		T pkt = new T();
		pkt.MergeFrom(buffer.Array, buffer.Offset + 4, buffer.Count - 4);

        CustomHandler(session, pkt, id);
	}

	public Action<PacketSession, IMessage> GetPacketHandler(ushort id)
	{
		Action<PacketSession, IMessage> action = null;
		if (_handler.TryGetValue(id, out action))
			return action;
		return null;
	}
}