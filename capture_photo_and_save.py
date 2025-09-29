import cv2
import os
import time
import pyodbc
from encode_save import encode_and_save  # Hàm này phải nhận (MaNV, image_path, conn)

# Thư mục lưu ảnh
folder = "photos"
os.makedirs(folder, exist_ok=True)

def capture_photo_and_save(nhanvien_id):
    # Khởi tạo camera tạm thời
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("❌ Không mở được camera")
        return False

    # Cho camera ổn định
    time.sleep(1)

    ret, frame = cap.read()
    cap.release()  # ⚡ Giải phóng camera ngay sau khi chụp

    if not ret or frame is None:
        print("❌ Không chụp được ảnh")
        return False

    # Lưu ảnh vào thư mục
    filename = os.path.join(folder, f"{nhanvien_id}_{int(time.time())}.jpg")
    cv2.imwrite(filename, frame)
    print(f"✅ Ảnh đã lưu: {filename}")

    # Kết nối SQL
    conn = pyodbc.connect(
        "Driver={SQL Server};"
        "Server=MINHHOP\\SQLEXPRESS;"
        "Database=FaceID;"
        "UID=sa;PWD=123456"   # ⚡ đồng bộ chuỗi kết nối
    )
    try:
        encode_and_save(nhanvien_id, filename, conn)
        print(f"✅ Đã lưu khuôn mặt vào DB cho nhân viên {nhanvien_id}")
    except Exception as e:
        print(f"❌ Lỗi khi encode và lưu vào DB: {e}")
    finally:
        conn.close()

    return filename
