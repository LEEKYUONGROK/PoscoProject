using UnityEngine;

public class PlayerMovement : MonoBehaviour
{
    [SerializeField] private Joystick joystick;
    [SerializeField] private Transform cameraTransform;
    [SerializeField] private float moveSpeed = 5f;

    private float fixedY;

    private void Start()
    {
        fixedY = transform.position.y;

        if (cameraTransform == null && Camera.main != null)
            cameraTransform = Camera.main.transform;
    }

    private void Update()
    {
        if (joystick == null || cameraTransform == null)
            return;

        Vector2 input = joystick.Direction;

        // 카메라의 전방을 XZ 평면에 투영 (Y축 제거)
        Vector3 forward = Vector3.ProjectOnPlane(
            cameraTransform.forward,
            Vector3.up
        ).normalized;

        // 카메라가 수직 아래를 바라보는 경우
        if (forward.sqrMagnitude < 0.001f)
        {
            forward = Vector3.ProjectOnPlane(
                cameraTransform.up,
                Vector3.up
            ).normalized;
        }

        // 카메라 기준 오른쪽 방향
        Vector3 right = Vector3.ProjectOnPlane(
            cameraTransform.right,
            Vector3.up
        ).normalized;

        // 카메라 회전을 반영한 이동 방향
        Vector3 moveDirection =
            forward * input.y +
            right * input.x;

        moveDirection = Vector3.ClampMagnitude(moveDirection, 1f);

        // 실제 이동
        Vector3 nextPosition = transform.position
            + moveDirection * moveSpeed * Time.deltaTime;

        // Y축 고정
        nextPosition.y = fixedY;

        transform.position = nextPosition;
    }
}