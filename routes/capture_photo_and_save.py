import cv2
import os
import time
import pyodbc
from core.face_utils import encode_and_save

FOLDER = "photos"
os.makedirs(FOLDER, exist_ok=True)

def capture_photo_and_save(ma_nv):
    print(f"\n Đang chụp ảnh cho nhân viên: {ma_nv}")

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("Không mở được camera!")
        return None

    # Cho camera khởi động ổn định
    time.sleep(2)

    best_frame = None
    best_brightness = 0.0

    # Chụp 10 khung hình, chọn ảnh sáng nhất (tự nhiên)
    for i in range(10):
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = gray.mean()

        if brightness > best_brightness:
            best_brightness = brightness
            best_frame = frame

        time.sleep(0.1)

    cap.release()

    # Nếu không có ảnh hợp lệ
    if best_frame is None:
        print("Không chụp được khung hình hợp lệ.")
        return None

    # Lật ảnh cho đúng hướng (như gương)
    best_frame = cv2.flip(best_frame, 1)

    # Lưu ảnh
    file_path = os.path.join(FOLDER, f"{ma_nv}.jpg")
    relative_path = f"{FOLDER}/{ma_nv}.jpg"
    success = cv2.imwrite(file_path, best_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])

    if not success:
        print("Lỗi khi lưu ảnh.")
        return None

    print(f" Ảnh đã lưu: {file_path} (brightness={best_brightness:.1f})")

    # --- Ghi DB ---
    try:
        conn = pyodbc.connect(
            "Driver={SQL Server};"
            "Server=MINHHOP\\SQLEXPRESS;"
            "Database=FaceID;"
            "UID=sa;PWD=123456"
        )
        cursor = conn.cursor()

        # Kiểm tra xem đã có khuôn mặt hoạt động chưa
        cursor.execute("SELECT COUNT(*) FROM KhuonMat WHERE MaNV=? AND TrangThai=1", (ma_nv,))
        exists = cursor.fetchone()[0]

        if exists:
            cursor.execute("""
                UPDATE KhuonMat
                SET DuongDanAnh=?, NgayDangKy=GETDATE(), MoTa=?
                WHERE MaNV=? AND TrangThai=1
            """, (relative_path, "Cập nhật ảnh tự nhiên khi thêm nhân viên", ma_nv))
            print(f"Cập nhật lại ảnh khuôn mặt cho {ma_nv}")
        else:
            cursor.execute("""
                INSERT INTO KhuonMat (MaNV, DuongDanAnh, TrangThai, NgayDangKy, MoTa)
                VALUES (?, ?, 1, GETDATE(), ?)
            """, (ma_nv, relative_path, "Ảnh tự nhiên chụp khi thêm nhân viên"))
            print(f"Thêm mới ảnh khuôn mặt cho {ma_nv}")

        conn.commit()
        print(f"Đã cập nhật DB cho {ma_nv}")

        # --- Encode khuôn mặt ---
        try:
            encode_and_save(ma_nv, file_path, conn)
            print(f"Đã encode khuôn mặt cho {ma_nv}")
        except Exception as enc_err:
            print(f"Không thể encode khuôn mặt: {enc_err}")

    except Exception as e:
        print(f"Lỗi khi ghi DB: {e}")
    finally:
        conn.close()

    return relative_path
