# attendance_system.py
import logging
import cv2
import face_recognition
import numpy as np
import pyodbc
from datetime import date, datetime, time
from db_utils import get_sql_connection


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("attendance_system")

# Nhân viên hiện tại (biến toàn cục)
current_employee = {"found": False}

# ======================
# SQL Connection
# ======================
def get_sql_connection():
    return pyodbc.connect(
        "Driver={SQL Server};"
        "Server=MINHHOP\\SQLEXPRESS;"
        "Database=FaceID;"
        "UID=sa;PWD=123456"
    )

# ======================
# Load dữ liệu khuôn mặt
# ======================
def load_known_faces():
    encodings, ids, names = [], [], []
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT k.MaNV, n.HoTen, k.MaHoaNhanDang
            FROM KhuonMat k
            JOIN NhanVien n ON k.MaNV = n.MaNV
            WHERE k.TrangThai = 1
        """)
        for row in cursor.fetchall():
            blob = row.MaHoaNhanDang
            if not blob:
                continue
            arr = np.frombuffer(blob, dtype=np.float64)
            if arr.size != 128:
                continue
            encodings.append(arr)
            ids.append(row.MaNV)
            names.append(row.HoTen)
        conn.close()
    except Exception:
        logger.exception("❌ Lỗi khi load known faces")
    logger.info("✅ Loaded %d known faces", len(encodings))
    return encodings, ids, names

# ======================
# Format thời gian
# ======================
def fmt_time_value(val):
    if val is None:
        return "-"
    if isinstance(val, (datetime, time)):
        return val.strftime("%H:%M:%S")
    return str(val)

def fmt_status(val):
    if val == 1:
        return "Đã chấm công"
    elif val == 0:
        return "Chưa chấm công"
    return str(val) if val else "Chưa chấm công"

# ======================
# Cập nhật nhân viên hiện tại
# ======================
# ======================
# Cập nhật nhân viên hiện tại
# ======================
current_employee = {}

def update_current_employee(ma_nv):
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MaNV, HoTen, MaPB, ChucVu 
            FROM NhanVien WHERE MaNV=? 
        """, (ma_nv,))
        row = cursor.fetchone()
        conn.close()

        if row:
            current_employee["MaNV"] = row.MaNV
            current_employee["HoTen"] = row.HoTen
            current_employee["PhongBan"] = row.MaPB
            current_employee["ChucVu"] = row.ChucVu
            current_employee["NgayChamCong"] = datetime.now().strftime("%Y-%m-%d")
            current_employee["GioVao"] = datetime.now().strftime("%H:%M:%S")
            current_employee["TrangThai"] = "Đã nhận diện"
        else:
            current_employee.clear()
    except Exception:
        logger.exception("❌ Lỗi khi cập nhật nhân viên hiện tại")
        current_employee.clear()

# ======================
# Chấm công tự động
# ======================
def record_attendance(ma_nv):
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()
        today = date.today().strftime("%Y-%m-%d")
        now_time = datetime.now().strftime("%H:%M:%S")

        # Kiểm tra đã chấm chưa
        cursor.execute("""
            SELECT COUNT(*) FROM ChamCong WHERE MaNV=? AND NgayChamCong=?
        """, (ma_nv, today))
        exists = cursor.fetchone()[0]

        if not exists:
            cursor.execute("""
                INSERT INTO ChamCong (MaNV, NgayChamCong, GioVao, TrangThai)
                VALUES (?, ?, ?, ?)
            """, (ma_nv, today, now_time, 1))
            conn.commit()
            logger.info("✅ Đã chấm công tự động cho MaNV=%s", ma_nv)

        conn.close()
    except Exception:
        logger.exception("❌ Lỗi khi chấm công cho MaNV=%s", ma_nv)

# ======================
# Xử lý frame
# ======================
def process_frame(frame, known_encodings, known_ids, known_names, tolerance=0.6):
    try:
        if frame is None:
            return frame

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_frame)
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
            name = "Unknown"
            ma_nv = None

            if known_encodings:
                distances = face_recognition.face_distance(known_encodings, face_encoding)
                best_match_index = np.argmin(distances)
                if distances[best_match_index] <= tolerance:
                    ma_nv = known_ids[best_match_index]
                    name = known_names[best_match_index]

                    update_current_employee(ma_nv)
                    record_attendance(ma_nv)

            # Vẽ khung + tên
            color = (0, 255, 0) if name != "Unknown" else (0, 0, 255)
            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
            cv2.putText(frame, name, (left, top - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        return frame
    except Exception:
        logger.exception("❌ Lỗi xử lý frame")
        return frame

# ======================
# Sinh frame stream cho Flask
# ======================
def generate_frames(known_encodings, known_ids, known_names):
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    while True:
        success, frame = camera.read()
        if not success:
            logger.error("❌ Không lấy được frame từ camera")
            break

        frame = process_frame(frame, known_encodings, known_ids, known_names)

        # Encode frame để stream qua Flask
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

    camera.release()
