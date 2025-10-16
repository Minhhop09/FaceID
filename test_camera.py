import cv2
for backend in [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_VFW, 0]:
    print(f"🧩 Thử backend: {backend}")
    cap = cv2.VideoCapture(0, backend)
    if cap.isOpened():
        print(f"✅ Camera mở được với backend {backend}")
        cap.release()
    else:
        print(f"❌ Không mở được camera với backend {backend}")
