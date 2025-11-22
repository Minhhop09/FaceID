import logging
import cv2
import face_recognition
import numpy as np
import pyodbc
from datetime import date, datetime
from core.db_utils import get_sql_connection
from PIL import ImageFont, ImageDraw, Image
from threading import Thread

# ============================================================
# ⚙️ Cấu hình logging
# ============================================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("attendance_system")

# ============================================================
# 🔸 Biến toàn cục
# ============================================================
current_employee = {}
last_recognized = {"name": None, "count": 0}
last_update_nv = None

# ============================================================
# 🧩 Kết nối SQL Server
# ============================================================
def get_sql_connection():
    return pyodbc.connect(
        "Driver={SQL Server};"
        "Server=MINHHOP\\SQLEXPRESS;"
        "Database=FaceID;"
        "UID=sa;PWD=123456"
    )

# ============================================================
# 📸 Load khuôn mặt đã đăng ký (Tự động chuyển sang chế độ Offline)
# ============================================================
def load_known_faces():
    import numpy as np, os, face_recognition, pickle
    encodings, ids, names = [], [], []

    try:
        # =================== 1️⃣ THỬ LẤY TỪ SQL SERVER ===================
        conn = get_sql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT k.MaNV, n.HoTen, k.MaHoaNhanDang
            FROM KhuonMat k
            JOIN NhanVien n ON k.MaNV = n.MaNV
            WHERE n.TrangThai = 1
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

        # ✅ Nếu load được ít nhất 1 khuôn mặt → lưu cache offline
        if encodings:
            with open("known_faces.pkl", "wb") as f:
                pickle.dump((encodings, ids, names), f)
            logger.info("Đã tải %d khuôn mặt hợp lệ từ SQL Server", len(encodings))
            return encodings, ids, names
        else:
            logger.warning("Không có dữ liệu khuôn mặt từ SQL Server, thử chế độ Offline...")

    except Exception as e:
        logger.warning(f"[OFFLINE] ⚠️ Không thể kết nối SQL Server ({e}), chuyển sang chế độ offline.")

    # =================== 2️⃣ CHẾ ĐỘ OFFLINE (KHI KHÔNG CÓ SQL) ===================
    # Ưu tiên dùng file cache nếu có
    if os.path.exists("known_faces.pkl"):
        try:
            with open("known_faces.pkl", "rb") as f:
                encodings, ids, names = pickle.load(f)
                logger.info(f"[OFFLINE] ⚡️ Đã tải {len(names)} khuôn mặt từ file known_faces.pkl")
                return encodings, ids, names
        except Exception as e:
            logger.warning(f"[OFFLINE] Không thể đọc cache known_faces.pkl: {e}")

    # Nếu không có file cache, load ảnh thô từ thư mục photos/
    photo_dir = os.path.join(os.getcwd(), "photos")
    if not os.path.exists(photo_dir):
        logger.warning("[OFFLINE] ❌ Không tìm thấy thư mục photos/")
        return [], [], []

    for filename in os.listdir(photo_dir):
        if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        ma_nv = os.path.splitext(filename)[0]
        img_path = os.path.join(photo_dir, filename)
        try:
            image = face_recognition.load_image_file(img_path)
            enc = face_recognition.face_encodings(image)
            if enc:
                encodings.append(enc[0])
                ids.append(ma_nv)
                names.append(ma_nv)
                logger.info(f"[OFFLINE] ✅ Tải {filename}")
        except Exception as e:
            logger.warning(f"[OFFLINE] ⚠️ Bỏ qua {filename}: {e}")

    logger.info(f"[OFFLINE] ✅ Đã tải {len(names)} khuôn mặt từ thư mục local (photos/)")
    return encodings, ids, names

# ============================================================
# 🧾 Cập nhật chấm công — FINAL FIXED V23
#  • Không ghi đè Manual
#  • Khóa camera 5 giây sau khi manual chấm công
#  • Ca đúng 100%
# ============================================================
def update_current_employee(ma_nv, ma_ca=None, source="camera", mode="in"):
    from flask import current_app
    from core.email_utils import notify_attendance
    from core.offline_cache import save_offline_record
    from datetime import datetime, time
    import pyodbc, time as _time

    global last_success, stable_faces, current_employee

    # Khởi tạo biến global
    if "last_success" not in globals():
        last_success = {}
    if "stable_faces" not in globals():
        stable_faces = {}

    print(f"[DEBUG] update_current_employee() → NV={ma_nv} | Ca={ma_ca} | Src={source} | Mode={mode}")

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    time_now  = now.strftime("%H:%M:%S")

    # ===================================
    # ❗ Không có MaCa → bỏ
    # ===================================
    if not ma_ca or str(ma_ca).strip() == "":
        print("[WARN] ❗ Thiếu MaCa → bỏ qua update")
        return

    KEY = (ma_nv, ma_ca, mode)

    # ===================================
    # 0️⃣ CHẶN CAMERA KHÔNG ĐƯỢC GHI ĐÈ MANUAL (5 GIÂY)
    # ===================================
    if source == "camera" and current_employee.get("manual_override", False):

        mt = current_employee.get("manual_time")
        if mt:
            delta = (now - mt).total_seconds()
            if delta < 5:
                print(f"[BLOCK] 🚫 Camera bị chặn {int(5 - delta)}s sau manual")
                return
            else:
                # Mở khóa sau 5 giây
                current_employee["manual_override"] = False
        else:
            print("[BLOCK] 🚫 manual_override nhưng không có manual_time → bỏ update camera")
            return

    # ===================================
    # 1️⃣ XỬ LÝ ỔN ĐỊNH CAMERA
    # ===================================
    if source == "camera":
        COOLDOWN = 30
        STABLE_COUNT = 12
        WINDOW = 2.5

        # Cooldown tránh spam
        if KEY in last_success:
            delta = (now - last_success[KEY]).total_seconds()
            if delta < COOLDOWN:
                print(f"[INFO] ⏳ Cooldown {int(COOLDOWN - delta)}s cho camera")
                return

        # Thu thập frame ổn định
        t = _time.time()
        stable_faces.setdefault(ma_nv, []).append(t)
        stable_faces[ma_nv] = [x for x in stable_faces[ma_nv] if t - x <= WINDOW]

        if len(stable_faces[ma_nv]) < STABLE_COUNT:
            print(f"[INFO] 👀 Camera chưa ổn định ({len(stable_faces[ma_nv])}/{STABLE_COUNT})")
            return

        print("[INFO] 🤝 Camera ổn định — bắt đầu ghi")
        stable_faces[ma_nv].clear()

    # ===================================
    # 2️⃣ GHI CHẤM CÔNG SQL
    # ===================================
    try:
        conn = get_sql_connection()
        if not conn:
            raise pyodbc.Error("SQL offline")

        cursor = conn.cursor()

        # --- 2.1 Lấy / tạo LichLamViec ---
        cursor.execute("""
            SELECT TOP 1 MaLLV
            FROM LichLamViec
            WHERE MaNV=? AND MaCa=? 
              AND CONVERT(date, NgayLam)=CONVERT(date, ?)
              AND DaXoa=1
        """, (ma_nv, ma_ca, today_str))
        row_llv = cursor.fetchone()

        if row_llv:
            ma_llv = row_llv[0]
        else:
            cursor.execute("""
                INSERT INTO LichLamViec (MaNV, MaCa, NgayLam, TrangThai, DaXoa)
                VALUES (?, ?, ?, 1, 1)
            """, (ma_nv, ma_ca, today_str))
            conn.commit()

            cursor.execute("SELECT SCOPE_IDENTITY()")
            ma_llv = cursor.fetchone()[0]

        # --- 2.2 Giờ bắt đầu ca ---
        cursor.execute("SELECT GioBatDau FROM CaLamViec WHERE MaCa=? AND TrangThai=1", (ma_ca,))
        row_bd = cursor.fetchone()
        gio_bd = row_bd[0] if row_bd else None

        # Chuẩn hóa giờ
        if isinstance(gio_bd, datetime):
            gio_bd = gio_bd.time()
        elif isinstance(gio_bd, str):
            s = gio_bd.split('.')[0]
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    gio_bd = datetime.strptime(s, fmt).time()
                    break
                except:
                    pass
        elif not isinstance(gio_bd, time):
            gio_bd = None

        # --- 2.3 Lấy ChamCong hiện tại ---
        cursor.execute("""
            SELECT TOP 1 MaChamCong, GioVao, GioRa
            FROM ChamCong
            WHERE MaNV=? AND MaCa=? 
              AND CONVERT(date, NgayChamCong)=CONVERT(date, ?)
              AND (DaXoa=1 OR DaXoa IS NULL)
            ORDER BY MaChamCong DESC
        """, (ma_nv, ma_ca, today_str))
        row_cc = cursor.fetchone()

        # ===================================
        # 3️⃣ VÀO CA
        # ===================================
        if mode == "in":
            trang_thai = 1
            status_text = "Đúng giờ"

            if gio_bd:
                diff = (datetime.combine(now.date(), now.time()) -
                        datetime.combine(now.date(), gio_bd)).total_seconds() / 60
                if diff > 0:
                    trang_thai = 2
                    status_text = f"Đi muộn {int(diff)} phút"
                elif diff < 0:
                    status_text = f"Vào sớm {abs(int(diff))} phút"

            if not row_cc:
                cursor.execute("""
                    INSERT INTO ChamCong (MaNV, MaLLV, MaCa, NgayChamCong, GioVao, TrangThai, DaXoa)
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                """, (ma_nv, ma_llv, ma_ca, now, now, trang_thai))
                conn.commit()

            else:
                _, gio_vao, gio_ra = row_cc
                if gio_vao and not gio_ra:
                    print("[INFO] ⚠️ Đã vào ca rồi.")
                    conn.close()
                    return

            cursor.execute("UPDATE LichLamViec SET TrangThai=? WHERE MaLLV=?",
                           (trang_thai, ma_llv))
            conn.commit()

            trang_thai_text = f"Vào ca ({status_text})"

        # ===================================
        # 4️⃣ RA CA
        # ===================================
        else:
            if not row_cc:
                print(f"[WARN] Chưa vào ca → không thể ra")
                conn.close()
                return

            ma_cc, gio_vao, gio_ra = row_cc

            if not gio_ra:
                cursor.execute("""
                    UPDATE ChamCong SET GioRa=?, TrangThai=4 WHERE MaChamCong=?
                """, (now, ma_cc))
                conn.commit()

            trang_thai_text = "Ra ca"

        # ===================================
        # 5️⃣ CẬP NHẬT UI
        # ===================================
        cursor.execute("""
            SELECT nv.HoTen, nv.ChucVu, pb.TenPB, clv.TenCa
            FROM NhanVien nv
            JOIN PhongBan pb ON nv.MaPB=pb.MaPB
            JOIN CaLamViec clv ON clv.MaCa=?
            WHERE nv.MaNV=?;
        """, (ma_ca, ma_nv))
        emp = cursor.fetchone()

        current_employee.clear()
        current_employee.update({
            "MaNV": ma_nv,
            "HoTen": emp[0],
            "PhongBan": emp[2],
            "ChucVu": emp[1],
            "CaLam": emp[3],
            "NgayChamCong": today_str,
            "GioVao": time_now if mode == "in" else "-",
            "GioRa": "-" if mode == "in" else time_now,
            "TrangThai": trang_thai_text,
            "found": True,

            # 🔥 camera KHÔNG được ghi đè nếu manual
            "manual_override": True if source == "manual" else False,
            "manual_time": datetime.now() if source == "manual" else None
        })

        print("[DEBUG] UI updated →", current_employee)

        # ===================================
        # 6️⃣ GỬI EMAIL
        # ===================================
        try:
            app = current_app._get_current_object()
            notify_attendance(
                ma_nv, trang_thai_text, now,
                ma_ca=ma_ca, source=source, app=app
            )
        except Exception as e:
            print("[WARN] Email lỗi:", e)

        last_success[KEY] = now
        conn.close()

    except Exception as e:
        print("[ERROR]", e)
        try:
            save_offline_record(ma_nv, today_str, ma_ca, time_now)
        except:
            pass

# ============================================================
# 🕒 Chấm công tự động (cho nút bấm hoặc test)
# ============================================================
def record_attendance(ma_nv, ma_ca):
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()
        today = date.today().strftime("%Y-%m-%d")
        now_time = datetime.now().strftime("%H:%M:%S")

        cursor.execute("SELECT TrangThai FROM NhanVien WHERE MaNV=?", (ma_nv,))
        nv_status = cursor.fetchone()
        if not nv_status or nv_status[0] != 1:
            return "Nhân viên không hợp lệ."

        cursor.execute("SELECT TenCa, GioBatDau, GioKetThuc FROM CaLamViec WHERE MaCa=?", (ma_ca,))
        ca = cursor.fetchone()
        if not ca:
            return f"Không tìm thấy ca {ma_ca}."
        ten_ca, gio_bat_dau, gio_ket_thuc = ca

        gio_bat_dau_dt = datetime.combine(datetime.today(), gio_bat_dau)
        now_dt_full = datetime.combine(datetime.today(), datetime.strptime(now_time, "%H:%M:%S").time())
        tre = (now_dt_full - gio_bat_dau_dt).total_seconds()
        trang_thai = 1 if tre <= 5 * 60 else 2

        # Lấy hoặc tạo LLV
        cursor.execute("""
            DECLARE @MaLLV INT;
            SELECT TOP 1 @MaLLV=MaLLV FROM LichLamViec
            WHERE MaNV=? AND MaCa=? AND NgayLam=? AND DaXoa=1;
            IF @MaLLV IS NULL
            BEGIN
                INSERT INTO LichLamViec (MaNV,MaCa,NgayLam,TrangThai,DaXoa)
                VALUES (?,?,?,1,1);
                SET @MaLLV=SCOPE_IDENTITY();
            END
            SELECT @MaLLV;
        """, (ma_nv, ma_ca, today, ma_nv, ma_ca, today))
        ma_llv_row = cursor.fetchone()
        ma_llv = ma_llv_row[0] if ma_llv_row else None

        cursor.execute("SELECT GioVao, GioRa FROM ChamCong WHERE MaNV=? AND NgayChamCong=? AND MaCa=?;",
                       (ma_nv, today, ma_ca))
        row = cursor.fetchone()

        if not row:
            cursor.execute("""
                INSERT INTO ChamCong (MaNV, MaLLV, MaCa, NgayChamCong, GioVao, TrangThai, DaXoa)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (ma_nv, ma_llv, ma_ca, today, now_time, trang_thai))
            conn.commit()
            status_text = f"Vào ca {ten_ca} ({'Đúng giờ' if trang_thai == 1 else 'Đi muộn'})"
        else:
            gio_vao, gio_ra = row
            if gio_ra is None:
                cursor.execute("""
                    UPDATE ChamCong SET GioRa=?, TrangThai=? 
                    WHERE MaNV=? AND NgayChamCong=? AND MaCa=?;
                """, (now_time, trang_thai, ma_nv, today, ma_ca))
                conn.commit()
                status_text = f"Ra ca {ten_ca} thành công"
            else:
                status_text = "Đã chấm công ca này rồi."

        conn.close()
        return status_text
    except Exception as e:
        logger.exception("Lỗi khi chấm công cho MaNV=%s", ma_nv)
        return f"Lỗi khi chấm công: {e}"
    
# ============================================================
# 📹 FINAL FIXED V21 — NHẬN DIỆN + CHẤM CÔNG CAMERA (KHÔNG GHI ĐÈ MANUAL)
# ============================================================
def process_frame(frame, known_encodings, known_ids, known_names, tolerance=0.6):
    from routes.attendance_system import update_current_employee
    from core.offline_cache import save_offline_record
    from core.db_utils import get_sql_connection
    from datetime import datetime, date
    import numpy as np
    import cv2
    from PIL import Image, ImageDraw, ImageFont

    global last_recognized, last_capture_time, current_employee

    # Init globals
    if "last_recognized" not in globals():
        last_recognized = {"name": None, "count": 0}
    if "last_capture_time" not in globals():
        last_capture_time = {}

    try:
        if frame is None:
            return frame

        # Convert
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_frame)
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        # Main processing
        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):

            name_display = "Không nhận diện"
            ma_nv = None
            status_text = ""

            # ============================
            # 1️⃣ So khớp khuôn mặt
            # ============================
            if known_encodings:
                distances = face_recognition.face_distance(known_encodings, face_encoding)
                best_match = np.argmin(distances)
                min_distance = distances[best_match]

                print(f"[DEBUG] Khoảng cách nhận diện = {min_distance:.2f}")

                if min_distance <= tolerance:
                    ma_nv = known_ids[best_match]
                    name_display = known_names[best_match]
                    print(f"[MATCH] {name_display} ({min_distance:.2f})")
                    status_text = f"Khớp ({min_distance:.2f})"

                    # =======================================
                    # 2️⃣ Lấy thông tin NV từ SQL (nếu online)
                    # =======================================
                    try:
                        conn = get_sql_connection()
                        cur = conn.cursor()
                        cur.execute("""
                            SELECT n.MaNV, n.HoTen, p.TenPB, n.ChucVu
                            FROM NhanVien n
                            LEFT JOIN PhongBan p ON n.MaPB=p.MaPB
                            WHERE n.MaNV=?
                        """, (ma_nv,))
                        row = cur.fetchone()
                        conn.close()

                        if row:
                            ho_ten = row.HoTen
                            ten_pb = row.TenPB
                            chuc_vu = row.ChucVu
                        else:
                            ho_ten = name_display
                            ten_pb = "-"
                            chuc_vu = "-"

                    except Exception:
                        # fallback offline
                        ho_ten = name_display
                        ten_pb = "-"
                        chuc_vu = "-"

                    # =====================================================
                    # 3️⃣ Xác định ca theo DB (thay vì Ca Full bị sai)
                    # =====================================================
                    try:
                        conn = get_sql_connection()
                        cur = conn.cursor()
                        now_str = datetime.now().strftime("%H:%M:%S")

                        cur.execute("""
                            SELECT TOP 1 MaCa, TenCa
                            FROM CaLamViec
                            WHERE ? BETWEEN GioBatDau AND GioKetThuc
                            AND TrangThai = 1   -- chỉ lấy ca đang hoạt động
                        """, (now_str,))
                        ca_row = cur.fetchone()
                        conn.close()

                        if ca_row:
                            ma_ca_hientai = ca_row.MaCa
                            ten_ca_hientai = ca_row.TenCa
                        else:
                            ma_ca_hientai = None
                            ten_ca_hientai = "-"
                    except:
                        # fallback offline
                        h = datetime.now().hour
                        if 6 <= h < 12:
                            ma_ca_hientai = "Ca1"
                            ten_ca_hientai = "Ca sáng"
                        elif 12 <= h < 18:
                            ma_ca_hientai = "Ca2"
                            ten_ca_hientai = "Ca chiều"
                        else:
                            ma_ca_hientai = "Ca3"
                            ten_ca_hientai = "Ca tối"

                    # =====================================================
                    # 4️⃣ Cập nhật UI — KHÔNG CHẤM CÔNG Ở ĐÂY
                    # =====================================================
                    current_employee.update({
                        "MaNV": ma_nv,
                        "HoTen": ho_ten,
                        "PhongBan": ten_pb,
                        "ChucVu": chuc_vu,
                        "CaLam": ten_ca_hientai,
                        "NgayChamCong": str(date.today()),
                        "GioVao": "-",
                        "GioRa": "-",
                        "TrangThai": "Chưa chấm công",
                        "found": True
                    })

                    # =============================================
                    # 5️⃣ Nhận diện ổn định → đủ 15 frame
                    # =============================================
                    if name_display == last_recognized["name"]:
                        last_recognized["count"] += 1
                    else:
                        last_recognized = {"name": name_display, "count": 1}

                    if last_recognized["count"] >= 15:

                        # =============================================
                        # 6️⃣ KHÔNG cho camera ghi đè manual
                        # =============================================
                        if current_employee.get("prevent_camera_override"):
                            print("[BLOCK] Camera không ghi đè manual")
                            continue

                        # =============================================
                        # 7️⃣ Chống spam 30s
                        # =============================================
                        now_time = datetime.now()
                        if ma_nv in last_capture_time:
                            delta = (now_time - last_capture_time[ma_nv]).total_seconds()
                            if delta < 30:
                                print(f"[INFO] ⏳ Bỏ qua {ma_nv}: {int(30 - delta)}s")
                                continue

                        last_capture_time[ma_nv] = now_time
                        print(f"[CAM] 📸 Ghi nhận tự động {name_display} [{ten_ca_hientai}]")

                        # =============================================
                        # 8️⃣ Gọi update_current_employee
                        # =============================================
                        try:
                            update_current_employee(
                                ma_nv,
                                ma_ca=ma_ca_hientai,
                                source="camera",
                                mode="in"
                            )
                        except Exception as e:
                            print("[OFFLINE] Lỗi SQL, lưu offline:", e)
                            try:
                                save_offline_record(
                                    ma_nv,
                                    now_time.strftime("%Y-%m-%d"),
                                    ma_ca_hientai,
                                    now_time.strftime("%H:%M:%S")
                                )
                            except:
                                pass

                else:
                    status_text = f"Không khớp ({min_distance:.2f})"

            # ===========================
            # 9️⃣ Vẽ khung nhận diện
            # ===========================
            color = (0, 255, 0) if ma_nv else (0, 0, 255)
            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)

            img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(img_pil)
            font = ImageFont.truetype("arial.ttf", 28)

            draw.text((left, top - 35), name_display, font=font, fill=(0, 255, 0))
            draw.text((left, bottom + 10), status_text, font=font, fill=(255, 255, 255))

            frame = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

        return frame

    except Exception as e:
        print("[ERROR FRAME]", e)
        return frame

# ============================================================
# 🔄 Stream video cho Flask
# ============================================================
def generate_frames(known_encodings, known_ids, known_names):
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not camera.isOpened():
        logger.error("Không mở được camera.")
        return

    frame_count = 0
    while True:
        success, frame = camera.read()
        if not success or frame is None:
            logger.warning("Không đọc được frame, thử khởi động lại camera...")
            camera.release()
            camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            continue

        frame = cv2.resize(frame, (640, 480))
        frame = process_frame(frame, known_encodings, known_ids, known_names)

        frame_count += 1
        if frame_count % 200 == 0:
            known_encodings, known_ids, known_names = load_known_faces()
            logger.info("Reloaded known faces")

        ret, buffer = cv2.imencode(".jpg", frame)
        if not ret:
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")

    camera.release()
