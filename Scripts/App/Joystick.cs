using UnityEngine;
using UnityEngine.EventSystems;

public class Joystick : MonoBehaviour,
    IPointerDownHandler,
    IDragHandler,
    IPointerUpHandler
{
    [SerializeField] private RectTransform handle;

    private RectTransform background;
    private Vector2 startPosition;

    public Vector2 Direction { get; private set; }

    private void Awake()
    {
        background = GetComponent<RectTransform>();
    }

    // 처음 터치한 위치 저장
    public void OnPointerDown(PointerEventData eventData)
    {
        if (!GetLocalPosition(eventData, out Vector2 position))
            return;

        // Background 중심 기준으로 변환
        startPosition = position - background.rect.center;

        // Handle을 처음 터치한 위치로 이동
        handle.anchoredPosition = startPosition;

        Direction = Vector2.zero;
    }

    // 드래그 중 이동
    public void OnDrag(PointerEventData eventData)
    {
        if (!GetLocalPosition(eventData, out Vector2 position))
            return;

        Vector2 currentPosition =
            position - background.rect.center;

        // 처음 터치한 위치로부터 이동 거리
        Vector2 delta = currentPosition - startPosition;

        Vector2 radius = background.rect.size * 0.5f;

        Direction = new Vector2(
            delta.x / radius.x,
            delta.y / radius.y
        );

        Direction = Vector2.ClampMagnitude(Direction, 1f);

        // 처음 터치 위치 기준으로 Handle 이동
        handle.anchoredPosition =
            startPosition +
            new Vector2(
                Direction.x * radius.x,
                Direction.y * radius.y
            );
    }

    // 손을 떼면 초기화
    public void OnPointerUp(PointerEventData eventData)
    {
        Direction = Vector2.zero;
        startPosition = Vector2.zero;
        handle.anchoredPosition = Vector2.zero;
    }

    private bool GetLocalPosition(
        PointerEventData eventData,
        out Vector2 position)
    {
        return RectTransformUtility
            .ScreenPointToLocalPointInRectangle(
                background,
                eventData.position,
                eventData.pressEventCamera,
                out position
            );
    }
}