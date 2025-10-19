import logging
import cv2
import face_recognition
import numpy as np
import pyodbc
from datetime import date, datetime
from db_utils import get_sql_connection
from PIL import ImageFont, ImageDraw, Image

# ==============================
# Cấu hình logging
# ==============================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("attendance_system")

# ====================================
# Biến toàn cục lưu nhân viên hiện tại
# ====================================
current_employee = {}
last_recognized = {"name": None, "count": 0}  # Dùng để ổn định nhận diện

# ======================
# Kết nối SQL Server
# ======================
def get_sql_connection():
    return pyodbc.connect(
        "Driver={SQL Server};"
        "Server=MINHHOP\\SQLEXPRESS;"
        "Database=FaceID;"
        "UID=sa;PWD=123456"
    )

# ======================
# Load khuôn mặt đã đăng ký
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
                logger.warning(f"Bỏ qua mã hóa không hợp lệ cho {row.HoTen} ({row.MaNV})")
                continue
            encodings.append(arr)
            ids.append(row.MaNV)
            names.append(row.HoTen)
        conn.close()
        logger.info("✅ Đã tải %d khuôn mặt hợp lệ", len(encodings))
    except Exception:
        logger.exception("❌ Lỗi khi load known faces")
    return encodings, ids, names

# ======================
# Cập nhật thông tin nhân viên hiện tại
# ======================
def update_current_employee(ma_nv, ma_ca=None):
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")

        if ma_ca:
            cursor.execute("""
                SELECT nv.MaNV, nv.HoTen, nv.MaPB, nv.ChucVu,
                       cc.MaCa, cc.GioVao, cc.GioRa, cc.TrangThai
                FROM NhanVien nv
                LEFT JOIN ChamCong cc 
                    ON nv.MaNV = cc.MaNV AND cc.NgayChamCong=? AND cc.MaCa=?
                WHERE nv.MaNV=?
            """, (today, ma_ca, ma_nv))
        else:
            cursor.execute("""
                SELECT TOP 1 nv.MaNV, nv.HoTen, nv.MaPB, nv.ChucVu,
                             cc.MaCa, cc.GioVao, cc.GioRa, cc.TrangThai
                FROM NhanVien nv
                LEFT JOIN ChamCong cc ON nv.MaNV = cc.MaNV AND cc.NgayChamCong=?
                WHERE nv.MaNV=?
                ORDER BY cc.GioVao DESC
            """, (today, ma_nv))

        row = cursor.fetchone()
        conn.close()

        if row:
            current_employee["MaNV"] = row.MaNV
            current_employee["HoTen"] = row.HoTen
            current_employee["PhongBan"] = row.MaPB
            current_employee["ChucVu"] = row.ChucVu
            current_employee["CaLam"] = row.MaCa or (ma_ca or "-")
            current_employee["NgayChamCong"] = today
            current_employee["GioVao"] = (
                row.GioVao.strftime("%H:%M:%S") if row.GioVao else "-"
            )
            current_employee["GioRa"] = (
                row.GioRa.strftime("%H:%M:%S") if row.GioRa else "-"
            )
            current_employee["TrangThai"] = "Đã nhận diện"
            current_employee["found"] = True
        else:
            current_employee.clear()
            current_employee["found"] = False

    except Exception:
        logger.exception("Lỗi khi cập nhật nhân viên hiện tại")
        current_employee.clear()
        current_employee["found"] = False


# ======================
# Chấm công tự động (nếu cần)
# ======================
def record_attendance(ma_nv, ma_ca):
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()
        today = date.today().strftime("%Y-%m-%d")
        now_time = datetime.now().strftime("%H:%M:%S")
        now_dt = datetime.strptime(now_time, "%H:%M:%S").time()

        # ===============================
        # 🔹 LẤY THÔNG TIN CA TỪ MÃ CA (bạn bấm chọn ca nào thì truyền vào)
        # ===============================
        cursor.execute("""
            SELECT TenCa, GioBatDau, GioKetThuc
            FROM CaLamViec
            WHERE MaCa = ?
        """, (ma_ca,))
        ca = cursor.fetchone()

        if not ca:
            conn.close()
            return f"⚠️ Không tìm thấy thông tin ca làm {ma_ca}."

        ten_ca, gio_bat_dau, gio_ket_thuc = ca

        # ===============================
        # 🔹 XÁC ĐỊNH TRẠNG THÁI: ĐÚNG GIỜ / ĐI MUỘN
        # ===============================
        gio_bat_dau_dt = datetime.combine(datetime.today(), gio_bat_dau)
        now_dt_full = datetime.combine(datetime.today(), now_dt)
        tre = (now_dt_full - gio_bat_dau_dt).total_seconds()
        trang_thai = 1 if tre <= 5 * 60 else 2  # <=5 phút: đúng giờ, ngược lại: đi muộn

        # ===============================
        # 🔹 ĐẢM BẢO LỊCH LÀM VIỆC CÓ BẢN GHI
        # ===============================
        cursor.execute("""
            IF NOT EXISTS (
                SELECT 1 FROM LichLamViec WHERE MaNV = ? AND NgayLam = ? AND MaCa = ?
            )
            INSERT INTO LichLamViec (MaNV, MaCa, NgayLam, TrangThai)
            VALUES (?, ?, ?, 1);
        """, (ma_nv, today, ma_ca, ma_nv, ma_ca, today))

        # ===============================
        # 🔹 KIỂM TRA ĐÃ CÓ BẢN GHI CHẤM CÔNG TRONG CA CHƯA
        # ===============================
        cursor.execute("""
            SELECT GioVao, GioRa FROM ChamCong
            WHERE MaNV = ? AND NgayChamCong = ? AND MaCa = ?
        """, (ma_nv, today, ma_ca))
        row = cursor.fetchone()

        # ===============================
        # 🔹 GHI NHẬN GIỜ VÀO / GIỜ RA
        # ===============================
        if not row:
            # ➕ Ghi giờ vào & lưu giờ ca thực tế (đóng băng)
            cursor.execute("""
                INSERT INTO ChamCong (
                    MaNV, NgayChamCong, GioVao, TrangThai, MaCa,
                    GioBatDauThucTe, GioKetThucThucTe
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (ma_nv, today, now_time, trang_thai, ma_ca, gio_bat_dau, gio_ket_thuc))

            # Cập nhật lịch làm việc thành "Đã chấm công"
            cursor.execute("""
                UPDATE LichLamViec
                SET TrangThai = 1
                WHERE MaNV = ? AND NgayLam = ? AND MaCa = ?
            """, (ma_nv, today, ma_ca))

            conn.commit()
            status_text = f"✅ Vào ca {ten_ca} ({'Đúng giờ' if trang_thai == 1 else 'Đi muộn'})"

        else:
            gio_vao, gio_ra = row
            if gio_ra is None:
                # ➕ Cập nhật giờ ra
                cursor.execute("""
                    UPDATE ChamCong
                    SET GioRa = ?, TrangThai = ?
                    WHERE MaNV = ? AND NgayChamCong = ? AND MaCa = ?
                """, (now_time, trang_thai, ma_nv, today, ma_ca))

                conn.commit()
                status_text = f"👋 Ra ca {ten_ca} thành công"
            else:
                status_text = "⚠️ Hôm nay đã chấm đủ cho ca này"

        conn.close()
        return status_text

    except Exception as e:
        logger.exception("❌ Lỗi khi chấm công cho MaNV=%s", ma_nv)
        return f"Lỗi khi chấm công: {str(e)}"

# ======================
# Xử lý từng frame camera
# ======================
def process_frame(frame, known_encodings, known_ids, known_names, tolerance=0.48):
    global last_recognized

    try:
        if frame is None:
            return frame

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_frame)
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
            name_display = "Không nhận diện"
            ma_nv = None
            status_text = ""

            if known_encodings:
                distances = face_recognition.face_distance(known_encodings, face_encoding)
                best_match_index = np.argmin(distances)
                min_distance = distances[best_match_index]

                if min_distance <= tolerance:
                    ma_nv = known_ids[best_match_index]
                    name_display = known_names[best_match_index]
                    update_current_employee(ma_nv)
                    status_text = f"Đã nhận diện ({min_distance:.2f})"
                else:
                    status_text = f"Không khớp ({min_distance:.2f})"

            # Bộ đếm ổn định (tránh nhấp nháy)
            if name_display == last_recognized["name"]:
                last_recognized["count"] += 1
            else:
                last_recognized = {"name": name_display, "count": 1}
            if last_recognized["count"] < 3:
                continue

            # Vẽ khung nhận diện
            color = (0, 255, 0) if ma_nv else (0, 0, 255)
            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)

            # Ghi tiếng Việt bằng Pillow
            img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(img_pil)
            font = ImageFont.truetype("arial.ttf", 28)
            draw.text((left, top - 35), name_display, font=font, fill=(0, 255, 0))
            draw.text((left, bottom + 10), status_text, font=font, fill=(255, 255, 255))
            frame = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

        return frame

    except Exception:
        logger.exception("Lỗi xử lý frame")
        return frame


# ======================
# Sinh frame stream cho Flask
# ======================
def generate_frames(known_encodings, known_ids, known_names):
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)

    if not camera.isOpened():
        logger.error("❌ Không mở được camera.")
        return

    frame_count = 0
    while True:
        success, frame = camera.read()

        if not success or frame is None:
            logger.warning("⚠️ Không đọc được frame, thử khởi động lại camera...")
            camera.release()
            camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            continue

        frame = cv2.resize(frame, (640, 480))
        frame = process_frame(frame, known_encodings, known_ids, known_names)

        frame_count += 1
        if frame_count % 200 == 0:  # Tự động reload sau ~10 giây
            known_encodings, known_ids, known_names = load_known_faces()
            logger.info("🔁 Reloaded known faces")

        ret, buffer = cv2.imencode(".jpg", frame)
        if not ret:
            logger.warning("⚠️ Không mã hóa được frame.")
            continue

        frame_bytes = buffer.tobytes()
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )

    camera.release()
