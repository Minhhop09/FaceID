import cv2
import os
import time
import pyodbc
from encode_save import encode_and_save

FOLDER = "photos"
os.makedirs(FOLDER, exist_ok=True)

def capture_photo_and_save(ma_nv):
    print(f"\n📸 Đang chụp ảnh cho nhân viên: {ma_nv}")

    # --- Dùng backend ổn định nhất cho Windows ---
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("❌ Không mở được camera!")
        return None

    # Cho camera ổn định nhanh (1 giây là đủ)
    time.sleep(1)

    # Đọc liên tiếp 10 frame trong 1 giây, lấy frame sáng nhất
    best_frame = None
    best_brightness = 0

    for i in range(10):
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        brightness = gray.mean()

        # Chọn frame sáng nhất
        if brightness > best_brightness:
            best_brightness = brightness
            best_frame = frame

        time.sleep(0.1)

    cap.release()

    # Kiểm tra kết quả
    if best_frame is None or best_brightness < 25:
        print(f"❌ Không chụp được khung hình hợp lệ (brightness={best_brightness:.1f})")
        return None

    # ✅ Lật ảnh ngang để đúng hướng gương mặt
    frame = cv2.flip(best_frame, 1)

    # Lưu ảnh
    file_path = os.path.join(FOLDER, f"{ma_nv}.jpg")
    relative_path = f"{FOLDER}/{ma_nv}.jpg"

    success = cv2.imwrite(file_path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    if not success:
        print("❌ Lỗi khi lưu ảnh.")
        return None

    print(f"✅ Ảnh đã lưu: {file_path} (brightness={best_brightness:.1f})")

    # --- Lưu DB ---
    try:
        conn = pyodbc.connect(
            "Driver={SQL Server};"
            "Server=MINHHOP\\SQLEXPRESS;"
            "Database=FaceID;"
            "UID=sa;PWD=123456"
        )

        #encode_and_save(ma_nv, file_path, conn)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM KhuonMat WHERE MaNV=?", (ma_nv,))
        exists = cursor.fetchone()[0]

        if exists:
            cursor.execute("""
                UPDATE KhuonMat
                SET DuongDanAnh=?, TrangThai=1, NgayDangKy=GETDATE(), MoTa=?
                WHERE MaNV=?
            """, (relative_path, "Ảnh tự động chụp khi thêm nhân viên", ma_nv))
        else:
            cursor.execute("""
                INSERT INTO KhuonMat (MaNV, DuongDanAnh, TrangThai, NgayDangKy, MoTa)
                VALUES (?, ?, 1, GETDATE(), ?)
            """, (ma_nv, relative_path, "Ảnh tự động chụp khi thêm nhân viên"))

        conn.commit()
        print(f"✅ Đã cập nhật DB cho {ma_nv}")

    except Exception as e:
        print(f"⚠️ Lỗi khi ghi DB: {e}")
    finally:
        conn.close()

    return relative_path
