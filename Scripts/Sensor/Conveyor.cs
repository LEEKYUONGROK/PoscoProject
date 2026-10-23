using Assets.TutorialInfo.Scripts;
using UnityEngine;

public class Conveyor : Sensor
{
    bool _OnSwitch = true;
    Animation animation = null;
    public override bool SwitchON
    {
        get { return _OnSwitch; }
        set
        {
            _OnSwitch = value;

            if (_OnSwitch)
                Resume();
            else
                Pause();
        }
    }
    public void Pause()
    {
        foreach (AnimationState state in animation)
            state.speed = 0f;
    }

    // 재개
    public void Resume()
    {
        foreach (AnimationState state in animation)
            state.speed = 1f;
    }

    public override void Init
        (int ID, int FactoryNum, int FloorNum, SensorType type = SensorType.Conveyor)
    {
        base.Init(ID, FactoryNum, FloorNum, type);

        animation = GetComponent<Animation>();
        if(animation == null)
        {
            Debug.LogError("애니메이션 Init 실패");
        }
    }
}
