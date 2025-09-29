import cv2

cap = cv2.VideoCapture(0)  # thử với 0
if not cap.isOpened():
    print("❌ Không mở được camera với index 0")
else:
    print("✅ Camera đã mở")

while True:
    ret, frame = cap.read()
    if not ret:
        print("❌ Không lấy được frame")
        break

    cv2.imshow("Test Camera", frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
