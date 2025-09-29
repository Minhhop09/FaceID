import cv2

camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)

def capture_image(save_path=None):
    """
    Chụp 1 frame từ camera global
    """
    global camera
    if not camera.isOpened():
        print("Không thể mở camera")
        return None

    ret, frame = camera.read()
    if not ret:
        print("❌ Không chụp được ảnh")
        return None

    if save_path:
        cv2.imwrite(save_path, frame)

    return frame
