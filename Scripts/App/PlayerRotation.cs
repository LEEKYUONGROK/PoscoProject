using UnityEngine;
using UnityEngine.EventSystems;

public class PlayerRotate : MonoBehaviour,IPointerDownHandler,
                            IPointerUpHandler
{
    [SerializeField] private Transform player;
    [SerializeField] private float rotationSpeed = 60f;
    [SerializeField] private bool isLeft = true;

    private bool isPressed = false;

    private void Update()
    {
        if (!isPressed || player == null)
            return;

        float direction = isLeft ? -1f : 1f;

        player.Rotate(0f,direction * rotationSpeed * Time.deltaTime,
            0f,Space.World);
    }

    // 버튼 누르기 시작
    public void OnPointerDown(PointerEventData eventData)
    {
        isPressed = true;
    }

    // 버튼에서 손을 떼면 정지
    public void OnPointerUp(PointerEventData eventData)
    {
        isPressed = false;
    }

    private void OnDisable()
    {
        isPressed = false;
    }
}