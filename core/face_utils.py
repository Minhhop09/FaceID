import os
import cv2
import numpy as np
import datetime
import time as tm
import face_recognition
from core.db_utils import get_connection

# HÀM CHÍNH: ENCODE KHUÔN MẶT & LƯU VÀO CSDL

def encode_and_save(nhanvien_id, image_path, conn):
    """
    Encode khuôn mặt từ ảnh và lưu vào bảng KhuonMat.
    - Kiểm tra độ sáng, tự tăng sáng nếu tối
    - Phát hiện khuôn mặt, crop vùng mặt
    - Encode khuôn mặt và lưu vào DB
    - Tự động update nếu khuôn mặt đã tồn tại
    """
    try:
        image_path = image_path.replace("\\", "/")

        # Kiểm tra file ảnh
        if not os.path.exists(image_path):
            print(f"File ảnh không tồn tại: {image_path}")
            return False

        print(f"Bắt đầu encode khuôn mặt cho {nhanvien_id}...")

        # Đọc ảnh gốc (BGR)
        img_bgr = cv2.imread(image_path)
        if img_bgr is None:
            print(f" Không thể đọc ảnh: {image_path}")
            return False

        # Tính độ sáng trung bình
        brightness = np.mean(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY))
        print(f"Độ sáng trung bình: {brightness:.1f}")

        # Tự động tăng sáng nhẹ nếu ảnh tối
        if brightness < 40:
            print(f"Ảnh hơi tối (brightness={brightness:.1f}) → tăng sáng nhẹ...")
            alpha, beta = 1.3, 35
            img_bgr = cv2.convertScaleAbs(img_bgr, alpha=alpha, beta=beta)
            cv2.imwrite(image_path, img_bgr)
            brightness = np.mean(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY))
            print(f"Ảnh sau khi tăng sáng: brightness={brightness:.1f}")

        # Chuyển sang RGB (thư viện face_recognition yêu cầu)
        img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

        # Phát hiện khuôn mặt (model = 'hog' nhanh hơn)
        face_locations = face_recognition.face_locations(img_rgb, model="hog")
        if len(face_locations) == 0:
            print(f"Không phát hiện khuôn mặt trong ảnh: {image_path}")
            try:
                os.remove(image_path)
                print(f"Đã xóa ảnh không hợp lệ: {image_path}")
            except Exception:
                pass
            return False

        # Crop vùng mặt đầu tiên để encode chính xác hơn
        (top, right, bottom, left) = face_locations[0]
        face_crop = img_rgb[top:bottom, left:right]
        if face_crop.size > 0:
            img_rgb = cv2.resize(face_crop, (250, 250))
            print(f"Đã crop khuôn mặt vùng ({left}, {top}) - ({right}, {bottom})")

        # Encode khuôn mặt
        encodings = face_recognition.face_encodings(img_rgb)
        if len(encodings) == 0:
            print(f"Không thể encode khuôn mặt: {image_path}")
            try:
                os.remove(image_path)
                print(f"Đã xóa ảnh không hợp lệ: {image_path}")
            except Exception:
                pass
            return False

        # Encode thành công
        face_encoding = encodings[0].tobytes()
        ngay_dang_ky = datetime.datetime.now()
        mo_ta = f"Tự động mã hóa khuôn mặt (brightness={brightness:.1f})"

        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM KhuonMat WHERE MaNV = ? AND TrangThai = 1", (nhanvien_id,))
        exists = cursor.fetchone()[0]

        if exists:
            # UPDATE nếu đã tồn tại
            cursor.execute("""
                UPDATE KhuonMat
                SET MaHoaNhanDang = ?, NgayDangKy = ?, MoTa = ?, DuongDanAnh = ?
                WHERE MaNV = ? AND TrangThai = 1
            """, (face_encoding, ngay_dang_ky, mo_ta, image_path, nhanvien_id))
            print(f"Cập nhật khuôn mặt cho {nhanvien_id}.")
        else:
            # INSERT nếu chưa có
            cursor.execute("""
                INSERT INTO KhuonMat (MaNV, DuongDanAnh, MaHoaNhanDang, NgayDangKy, TrangThai, MoTa)
                VALUES (?, ?, ?, ?, 1, ?)
            """, (nhanvien_id, image_path, face_encoding, ngay_dang_ky, mo_ta))
            print(f"Thêm mới khuôn mặt cho {nhanvien_id}.")

        conn.commit()
        print(f"Đã encode và lưu khuôn mặt cho {nhanvien_id}.")
        return True

    except Exception as e:
        print(f"Lỗi khi encode khuôn mặt: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False

# HÀM ENCODE NỀN (ASYNC) — CHẠY SONG SONG KHI THÊM NHÂN VIÊN

def async_encode_face(ma_nv, image_path):
    """
    Hàm chạy nền để mã hoá khuôn mặt nhân viên.
    Dùng khi thêm nhân viên mới để không chặn luồng chính.
    """
    conn = get_connection()
    try:
        print(f"[THREAD] Bắt đầu encode nền cho {ma_nv}...")
        start = tm.time()

        image_path = image_path.replace("\\", "/")
        if not os.path.exists(image_path):
            print(f"[THREAD] Ảnh không tồn tại: {image_path}")
            return

        image = face_recognition.load_image_file(image_path)
        encodings = face_recognition.face_encodings(image)

        if not encodings:
            print(f"[THREAD] Không thể encode khuôn mặt cho {ma_nv}.")
            return

        face_encoding = encodings[0].tobytes()
        cursor = conn.cursor()
        cursor.execute("""
            IF EXISTS(SELECT 1 FROM KhuonMat WHERE MaNV=? AND TrangThai=1)
                UPDATE KhuonMat
                SET MaHoaNhanDang=?, NgayDangKy=GETDATE(), MoTa=N'Encode nền'
                WHERE MaNV=? AND TrangThai=1
            ELSE
                INSERT INTO KhuonMat (MaNV, MaHoaNhanDang, TrangThai, NgayDangKy, MoTa)
                VALUES (?, ?, 1, GETDATE(), N'Encode nền')
        """, (ma_nv, face_encoding, ma_nv, ma_nv, face_encoding))
        conn.commit()
        print(f"[THREAD] Encode nền hoàn tất cho {ma_nv} ({tm.time() - start:.2f}s)")

    except Exception as e:
        print(f"[THREAD] Lỗi encode nền: {e}")
    finally:
        conn.close()

# HÀM STREAM CAMERA & NHẬN DIỆN KHUÔN MẶT

def generate_frames(known_encodings, known_ids, known_names):
    """
    Mở camera, nhận diện khuôn mặt theo danh sách known_encodings.
    Trả về luồng ảnh (frame) cho Flask Response.
    """
    camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        print("Không mở được camera.")
        return

    print("Camera đang chạy...")

    while True:
        success, frame = camera.read()
        if not success:
            print("Không thể đọc khung hình từ camera.")
            break

        # Giảm kích thước cho nhanh
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

        # Phát hiện khuôn mặt trong khung hình
        face_locations = face_recognition.face_locations(rgb_small_frame)
        face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
            # So sánh với danh sách known_encodings
            matches = face_recognition.compare_faces(known_encodings, face_encoding)
            name = "Không xác định"

            if True in matches:
                matched_idx = np.argmin(face_recognition.face_distance(known_encodings, face_encoding))
                name = known_names[matched_idx]

            # Vẽ khung nhận diện
            top *= 4
            right *= 4
            bottom *= 4
            left *= 4

            color = (0, 255, 0) if name != "Không xác định" else (0, 0, 255)
            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
            cv2.rectangle(frame, (left, bottom - 35), (right, bottom), color, cv2.FILLED)
            cv2.putText(frame, name, (left + 6, bottom - 6),
                        cv2.FONT_HERSHEY_DUPLEX, 0.8, (255, 255, 255), 1)

        # Encode frame → gửi về trình duyệt
        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    camera.release()
    print("Camera đã dừng.")
