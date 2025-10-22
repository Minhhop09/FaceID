from flask import Flask, render_template, request, redirect, url_for, flash, Response, session, jsonify, Blueprint
import pyodbc
import hashlib
import atexit
from datetime import datetime
import cv2
from add_employee import generate_ma_nv, add_new_employee
from db_utils import get_phongbans
from capture_photo_and_save import capture_photo_and_save
from encode_save import encode_and_save
from attendance_system import process_frame, load_known_faces, generate_frames, record_attendance, current_employee as att_current_employee, update_current_employee, current_employee
from db_utils import get_sql_connection
import manage_department
import manage_shift
import manage_account
import reports
import os
from werkzeug.utils import secure_filename
from db_utils import find_employees_by_name_or_manv
from flask import send_from_directory
from collections import Counter
from flask import render_template
from werkzeug.utils import secure_filename
import base64
from PIL import ImageFont, ImageDraw, Image
from flask import send_from_directory
from db_utils import get_connection
from flask import request, redirect, url_for, flash, render_template, session
from flask import send_file
from docx import Document
import io
from openpyxl import Workbook
from manage_account import add_account 
import datetime as dt
import time as tm
import traceback



# Config Flask

app = Flask(__name__)
app.secret_key = "faceid_secret"
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 

# SQL Connection
def get_sql_connection():
    conn = pyodbc.connect(
        "Driver={SQL Server};"
        "Server=MINHHOP\\SQLEXPRESS;"
        "Database=FaceID;"
        "UID=sa;PWD=123456"
    )
    # Gắn user hiện tại ngay sau khi kết nối
    cursor = conn.cursor()
    try:
        username = session.get('username') or session.get('user_id') or 'admin'
        cursor.execute("EXEC sys.sp_set_session_context @key=N'user', @value=?", (username,))
        conn.commit()
    except:
        pass  # nếu không có session (trang công khai) thì bỏ qua
    return conn

from functools import wraps

def require_role(role):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # Chưa đăng nhập thì quay lại login
            if "username" not in session:
                flash("Vui lòng đăng nhập để truy cập hệ thống", "warning")
                return redirect(url_for("login"))

            # Sai vai trò thì cấm truy cập
            if session.get("role") != role:
                flash("Bạn không có quyền truy cập trang này!", "danger")
                return redirect(url_for("index"))

            return f(*args, **kwargs)
        return wrapper
    return decorator


def safe_date_format(value):
    """Chuyển đổi giá trị ngày (datetime hoặc string) thành định dạng dd/mm/yyyy"""
    if not value:
        return "—"
    # Nếu là string, thử parse sang datetime
    if isinstance(value, str):
        # Thử các định dạng phổ biến
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
            except ValueError:
                continue
        return value  # nếu không parse được, trả về nguyên văn
    # Nếu là datetime thật
    try:
        return value.strftime("%d/%m/%Y")
    except Exception:
        return str(value)

# Camera global (singleton)

camera = None
def get_camera():
    global camera
    if camera is None or not camera.isOpened():
        camera = cv2.VideoCapture(0, cv2.CAP_MSMF) 
        if not camera.isOpened():
            print("Không mở được camera")
            return None
    return camera

# Face encodings

known_encodings, known_ids, known_names = load_known_faces()

# Camera stream CHẤM CÔNG

@app.route('/video_feed')
def video_feed():
    encodings, ids, names = load_known_faces()
    return Response(
        generate_frames(encodings, ids, names),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

# Camera stream ĐĂNG KÝ

@app.route('/register_feed')
def register_feed():
    def gen_register_cam():
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            _, buffer = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        cap.release()

    return Response(gen_register_cam(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

# Chấm công thủ công

def record_manual_attendance(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    time_now = now.strftime("%H:%M:%S")

    cursor.execute("SELECT COUNT(*) FROM ChamCong WHERE MaNV=? AND NgayChamCong=?", (ma_nv, today))
    exists = cursor.fetchone()[0]
    if exists:
        conn.close()
        raise Exception("Nhân viên đã chấm công hôm nay!")

    cursor.execute("""
        INSERT INTO ChamCong (MaNV, NgayChamCong, GioVao, TrangThai)
        VALUES (?, ?, ?, ?)
    """, (ma_nv, today, time_now, 1))
    conn.commit()
    conn.close()

# ĐĂNG NHẬP HỆ THỐNG

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu", "danger")
            return redirect(url_for("login"))

        #Băm mật khẩu SHA-256
        import hashlib
        password_hash = hashlib.sha256(password.encode()).hexdigest()

        #Kết nối SQL Server
        conn = get_sql_connection()
        cursor = conn.cursor()

        #Kiểm tra tài khoản hợp lệ và lấy thông tin nhân viên
        cursor.execute("""
            SELECT tk.TenDangNhap, tk.VaiTro, tk.TrangThai, nv.MaNV, nv.HoTen, nv.Email
            FROM TaiKhoan tk
            LEFT JOIN NhanVien nv ON tk.MaNV = nv.MaNV
            WHERE tk.TenDangNhap = ? AND tk.MatKhauHash = ?
        """, (username, password_hash))

        user = cursor.fetchone()
        conn.close()

        if user:
            ten_dang_nhap, vai_tro, trang_thai, ma_nv, ho_ten, email = user

            if trang_thai != 1:
                flash("Tài khoản này đang bị khóa!", "danger")
                return redirect(url_for("login"))

            #Lưu session
            session["username"] = ten_dang_nhap
            session["role"] = vai_tro
            session["manv"] = ma_nv
            session["hoten"] = ho_ten
            session["email"] = email

            #Điều hướng theo vai trò
            if vai_tro.lower() == "admin":
                return redirect(url_for("admin_dashboard"))
            elif vai_tro.lower() == "nhanvien":
                return redirect(url_for("employee_dashboard"))
            else:
                flash("Tài khoản không có vai trò hợp lệ!", "warning")
                return redirect(url_for("login"))
        else:
            flash("Sai tên đăng nhập hoặc mật khẩu", "danger")
            return redirect(url_for("login"))

    return render_template("login.html")

# Trang chính

@app.route("/")
@app.route("/index")
def index():
    return render_template("index.html")

# Trang đăng ký nhân viên
# 🧩 HÀM SINH MÃ NHÂN VIÊN
# ===============================
def generate_employee_code(conn):
    cur = conn.cursor()
    cur.execute("SELECT MAX(MaNV) FROM NhanVien WHERE MaNV LIKE 'NV_____'")
    last = cur.fetchone()[0]
    if last:
        try:
            num = int(last[2:]) + 1
        except Exception:
            num = 1
    else:
        num = 1
    return f"NV{num:05d}"


# ===============================
# 🧩 TRANG ĐĂNG KÝ NHÂN VIÊN
# ===============================
@app.route("/register", methods=["GET", "POST"])
def register():
    phongbans = get_phongbans()

    if request.method == "POST":
        hoten = request.form.get("HoTen", "").strip()
        email = request.form.get("Email", "").strip()
        sdt = request.form.get("SDT", "").strip()
        gioitinh_input = request.form.get("GioiTinh", "").strip().lower()
        ngaysinh = request.form.get("NgaySinh", "").strip()
        diachi = request.form.get("DiaChi", "").strip()
        ma_pb = request.form.get("PhongBan", "").strip()
        chucvu = request.form.get("ChucVu", "").strip()

        if not hoten or not email or not ma_pb:
            flash("⚠️ Vui lòng điền đầy đủ thông tin bắt buộc!", "danger")
            return redirect(url_for("register"))

        gioitinh = 1 if gioitinh_input == "nam" else 0 if gioitinh_input == "nữ" else None
        if gioitinh is None:
            flash("⚠️ Giới tính không hợp lệ. Vui lòng nhập 'Nam' hoặc 'Nữ'.", "danger")
            return redirect(url_for("register"))

        conn = get_connection()
        cursor = conn.cursor()

        try:
            start_all = tm.time()
            today_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ngay_sinh_str = ngaysinh if ngaysinh else None
            ma_nv_moi = generate_employee_code(conn)

            # 🔹 1. Thêm nhân viên mới
            cursor.execute("""
                INSERT INTO NhanVien (
                    MaNV, MaHienThi, HoTen, Email, SDT, GioiTinh, NgaySinh, DiaChi,
                    MaPB, ChucVu, TrangThai, NgayVaoLam, NgayNghiViec, NgayTao
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ma_nv_moi, ma_nv_moi, hoten, email, sdt, gioitinh, ngay_sinh_str, diachi,
                ma_pb, chucvu, 1, today_str, None, today_str
            ))
            print(f"🧩 Đã thêm nhân viên {ma_nv_moi} vào NhanVien.")

            # 🔹 2. Nếu là quản lý → cập nhật phòng ban
            capbac = {"Giám đốc": 1, "Trưởng phòng": 2, "Quản lý": 3}
            if chucvu in capbac:
                cursor.execute("""
                    SELECT nv.MaNV, nv.ChucVu
                    FROM PhongBan pb
                    LEFT JOIN NhanVien nv ON pb.QuanLyPB = nv.MaNV
                    WHERE pb.MaPB = ?
                """, (ma_pb,))
                current_manager = cursor.fetchone()

                current_rank = capbac.get(current_manager[1], 999) if current_manager and current_manager[1] else 999
                new_rank = capbac.get(chucvu, 999)

                if not current_manager or new_rank < current_rank:
                    cursor.execute("""
                        UPDATE PhongBan
                        SET QuanLyPB = ?
                        WHERE MaPB = ?
                    """, (ma_nv_moi, ma_pb))
                    print(f"🏢 Cập nhật {ma_nv_moi} làm quản lý phòng {ma_pb}.")
                conn.commit()

            # 🔹 3. Chụp ảnh khuôn mặt
            start_capture = tm.time()
            image_path = capture_photo_and_save(ma_nv_moi)
            print(f"📸 Thời gian chụp ảnh: {tm.time() - start_capture:.2f}s")

            if image_path:
                start_encode = tm.time()
                encode_success = encode_and_save(ma_nv_moi, image_path, conn)
                print(f"⏱️ Thời gian encode: {tm.time() - start_encode:.2f}s")

                if encode_success:
                    global known_encodings, known_ids, known_names
                    known_encodings, known_ids, known_names = load_known_faces()
                    print(f"✅ Encode xong và nạp khuôn mặt {ma_nv_moi}.")
                else:
                    flash(f"⚠️ Không phát hiện được khuôn mặt hợp lệ cho {hoten}.", "warning")

            conn.commit()
            print(f"🕒 Tổng thời gian đăng ký: {tm.time() - start_all:.2f}s")
            flash(f"✅ Nhân viên {hoten} ({chucvu}) đã được thêm thành công vào phòng {ma_pb}!", "success")

        except Exception as e:
            conn.rollback()
            import sys
            print("❌ LỖI ĐĂNG KÝ CHI TIẾT:")
            traceback.print_exc(file=sys.stdout)
            print("⚠️ Kiểu lỗi:", type(e))
            print("⚠️ Nội dung lỗi:", str(e))
            flash(f"❌ Lỗi khi thêm nhân viên: {e}", "danger")
        finally:
            conn.close()

        return redirect(url_for("register"))

    return render_template("register.html", phongbans=phongbans)


# API lấy nhân viên gần nhất

@app.route("/get_current_employee")
def get_current_employee():
    if current_employee:
        return jsonify({
            "found": True,
            "MaNV": current_employee.get("MaNV"),
            "HoTen": current_employee.get("HoTen"),
            "PhongBan": current_employee.get("PhongBan"),
            "NgayChamCong": current_employee.get("NgayChamCong"),
            "GioVao": current_employee.get("GioVao"),
            "GioRa": current_employee.get("GioRa"),
            "CaLam": current_employee.get("CaLam", "-"),
            "TrangThai": current_employee.get("TrangThai")
        })
    return jsonify({"found": False})

# Trang chấm công

@app.route("/attendance")
def attendance():
   
    return render_template("attendance.html")

@app.route("/attendance_feed")
def attendance_feed():
    known_encodings, known_ids, known_names = load_known_faces()
    return Response(
        generate_frames(known_encodings, known_ids, known_names),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

# Chấm công thủ công

@app.route("/manual_attendance", methods=["POST"])
def manual_attendance():
    ma_nv = request.form.get("ma_nv")
    mode = request.form.get("mode")      # 'in' hoặc 'out'
    ma_ca = request.form.get("ma_ca")    # 'Ca1', 'Ca2', 'Ca3'

    if not ma_nv:
        flash("Không tìm thấy nhân viên!", "danger")
        return redirect(url_for("attendance"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    now_time = datetime.now().strftime("%H:%M:%S")

    # 🔹 Lấy MaLLV tương ứng trong LichLamViec
    cursor.execute("""
        SELECT TOP 1 MaLLV
        FROM LichLamViec
        WHERE MaNV = ? AND MaCa = ? AND NgayLam = ? AND DaXoa = 1
    """, (ma_nv, ma_ca, today))
    result = cursor.fetchone()
    ma_llv = result[0] if result else None

    # Kiểm tra xem đã có bản ghi chấm công chưa
    cursor.execute("""
        SELECT GioVao, GioRa FROM ChamCong
        WHERE MaNV=? AND NgayChamCong=? AND MaCa=?
    """, (ma_nv, today, ma_ca))
    row = cursor.fetchone()

    if not row:
        if mode == "in":
            cursor.execute("""
                INSERT INTO ChamCong (MaNV, MaLLV, MaCa, NgayChamCong, GioVao, TrangThai, DaXoa)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (ma_nv, ma_llv, ma_ca, today, now_time, 1))
            conn.commit()
            flash(f"{ma_ca} - Vào ca lúc {now_time}", "success")
        else:
            flash("Chưa vào ca này, không thể ra ca!", "warning")
    else:
        gio_vao, gio_ra = row
        if mode == "in":
            flash(f"Đã chấm vào {ma_ca} rồi!", "warning")
        elif mode == "out":
            if gio_ra:
                flash(f"Đã ra ca {ma_ca} rồi!", "warning")
            else:
                cursor.execute("""
                    UPDATE ChamCong 
                    SET GioRa=?, TrangThai=2
                    WHERE MaNV=? AND NgayChamCong=? AND MaCa=?
                """, (now_time, ma_nv, today, ma_ca))
                conn.commit()
                flash(f"{ma_ca} - Ra ca lúc {now_time}", "success")

    conn.close()

    # Cập nhật lại thông tin hiển thị bên phải
    update_current_employee(ma_nv, ma_ca)
    return redirect(url_for("attendance"))


# Trang Admin

@app.route('/admin')
@require_role("admin")
def admin_dashboard():
    if 'role' in session and session['role'] == 'admin':
        conn = get_sql_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM NhanVien WHERE TrangThai = 1")
        total_employees = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE TrangThai = 1")
        total_departments = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM CaLamViec WHERE TrangThai = 1")
        total_shifts = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM TaiKhoan WHERE TrangThai = 1")
        total_accounts = cursor.fetchone()[0]

        conn.close()

        return render_template(
            'admin.html',
            total_employees=total_employees,
            total_departments=total_departments,
            total_shifts=total_shifts,
            total_accounts=total_accounts,
            last_login=session.get('last_login', 'Không xác định')
        )
    else:
        flash("Bạn không có quyền truy cập!", "danger")
        return redirect(url_for('login'))


# Giải phóng camera khi app dừng

def close_camera():
    global camera
    if camera and camera.isOpened():
        camera.release()
        print("Camera đã được giải phóng")

atexit.register(close_camera)

@app.teardown_appcontext
def cleanup(exception=None):
    if camera and camera.isOpened():
        camera.release()

UPLOAD_FOLDER = os.path.join("static", "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

def allowed_file(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/faces")
@require_role("admin")
def faces():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                k.FaceID,
                k.MaNV,
                nv.HoTen,
                pb.TenPB,
                k.DuongDanAnh,
                k.NgayDangKy,
                k.TrangThai,
                k.MoTa
            FROM KhuonMat k
            JOIN NhanVien nv ON k.MaNV = nv.MaNV
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            WHERE k.TrangThai = 1     -- ✅ Chỉ lấy khuôn mặt đang hoạt động
            ORDER BY k.NgayDangKy DESC
        """)
        faces = cursor.fetchall()
    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách khuôn mặt: {e}", "error")
        faces = []
    finally:
        conn.close()

    return render_template("faces.html", faces=faces)

# ============================================================
# 🧍 DANH SÁCH KHUÔN MẶT NHÂN VIÊN BỊ XÓA MỀM
# ============================================================
@app.route("/faces/deleted")
@require_role("admin")
def deleted_faces():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                k.FaceID,
                k.MaNV,
                nv.HoTen,
                pb.TenPB,
                k.DuongDanAnh,
                k.NgayDangKy,
                k.TrangThai,
                k.MoTa
            FROM KhuonMat k
            JOIN NhanVien nv ON k.MaNV = nv.MaNV
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            WHERE nv.TrangThai = 0 OR k.TrangThai = 0
            ORDER BY k.NgayDangKy DESC
        """)
        deleted_faces = cursor.fetchall()
    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách khuôn mặt bị xóa mềm: {e}", "error")
        deleted_faces = []
    finally:
        conn.close()

    return render_template("deleted_records.html", deleted_faces=deleted_faces)


@app.route("/employees")
@require_role("admin")
def employee_list():
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy tham số tìm kiếm và sắp xếp ---
    keyword = request.args.get("q", "").strip()
    sort = request.args.get("sort", "ma")  # kiểu sắp xếp: ma, ten, phongban, chucvu
    order = request.args.get("order", "asc")  # thứ tự: asc hoặc desc

    # --- Lấy danh sách nhân viên ---
    query = """
        SELECT nv.MaNV, nv.HoTen, nv.Email, nv.ChucVu, nv.NgaySinh, pb.TenPB, km.DuongDanAnh
        FROM NhanVien nv
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat km ON nv.MaNV = km.MaNV
        WHERE nv.TrangThai = 1  -- ✅ chỉ lấy nhân viên chưa bị xóa mềm
    """
    params = []

    if keyword:
        query += """
            AND (nv.HoTen LIKE ? 
                 OR nv.MaNV LIKE ?
                 OR nv.ChucVu LIKE ?
                 OR pb.TenPB LIKE ?)
        """
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

    # --- Xử lý sắp xếp ---
    sort_map = {
        "ma": "nv.MaNV",
        "ten": "nv.HoTen",
        "phongban": "pb.TenPB",
        "chucvu": "nv.ChucVu"
    }
    sort_col = sort_map.get(sort, "nv.MaNV")
    order_sql = "ASC" if order == "asc" else "DESC"
    query += f" ORDER BY {sort_col} {order_sql}"

    # --- Thực thi ---
    cursor.execute(query, params)
    rows = cursor.fetchall()
    columns = [column[0] for column in cursor.description]

    employees = []
    for row in rows:
        emp = dict(zip(columns, row))
        avatar = emp.get("DuongDanAnh")
        if avatar and avatar.strip():
            avatar = avatar.replace("\\", "/")
            emp["Avatar"] = f"/{avatar}" if not avatar.startswith("/") else avatar
        else:
            emp["Avatar"] = "/static/photos/default.jpg"
        employees.append(emp)

    # --- Thống kê ---
    cursor.execute("SELECT COUNT(*) FROM NhanVien WHERE TrangThai = 1")
    total_employees = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE TrangThai = 1")
    total_departments = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM NhanVien WHERE ChucVu LIKE N'%Trưởng phòng%' AND TrangThai = 1")
    total_managers = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM NhanVien
        WHERE TrangThai = 1
          AND TRY_CONVERT(DATE, NgaySinh, 103) IS NOT NULL
          AND MONTH(TRY_CONVERT(DATE, NgaySinh, 103)) = MONTH(GETDATE())
    """)
    birthday_this_month = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "employees.html",
        employees=employees,
        total_employees=total_employees,
        total_departments=total_departments,
        total_managers=total_managers,
        birthday_this_month=birthday_this_month,
        keyword=keyword,
        sort=sort,
        order=order
    )


#chi tiết nhân viên

@app.route("/employees/<ma_nv>")
@require_role("admin")
def employee_detail(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy thông tin nhân viên đầy đủ ---
    cursor.execute("""
        SELECT 
            nv.MaNV,
            nv.MaHienThi,
            nv.HoTen,
            nv.Email,
            nv.SDT,
            nv.GioiTinh,
            nv.NgaySinh,
            nv.DiaChi,
            pb.TenPB AS TenPhongBan,
            nv.ChucVu,
            nv.TrangThai,
            nv.NgayVaoLam,
            nv.NgayTao,
            nv.NgayCapNhat,

            km.DuongDanAnh
        FROM NhanVien nv
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat km ON nv.MaNV = km.MaNV
        WHERE nv.MaNV = ?
    """, (ma_nv,))
    
    row = cursor.fetchone()
    if not row:
        conn.close()
        flash("Không tìm thấy nhân viên!", "error")
        return redirect(url_for("employee_list"))

    # --- Chuyển kết quả thành dict ---
    columns = [col[0] for col in cursor.description]
    employee = dict(zip(columns, row))

    # --- Hàm định dạng ngày ---
    def format_date(value):
        if not value:
            return "—"
        try:
            if isinstance(value, str):
                return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
            else:
                return value.strftime("%d/%m/%Y")
        except Exception:
            return str(value)

    # --- Xử lý các ngày ---
    employee["NgaySinh"] = format_date(employee.get("NgaySinh"))
    employee["NgayVaoLam"] = format_date(employee.get("NgayVaoLam"))
    employee["NgayTao"] = format_date(employee.get("NgayTao"))
    employee["NgayCapNhat"] = format_date(employee.get("NgayCapNhat"))


    # --- Xử lý giới tính ---
    employee["GioiTinhText"] = "Nam" if employee.get("GioiTinh") == 1 else "Nữ"

    # --- Xử lý avatar ---
    avatar = employee.get("DuongDanAnh")
    if avatar and avatar.strip():
        avatar = avatar.replace("\\", "/")
        if not avatar.startswith("/"):
            employee["AnhDaiDien"] = f"/{avatar}"  # ví dụ: /photos/NVTC7.jpg
        else:
            employee["AnhDaiDien"] = avatar
    else:
        employee["AnhDaiDien"] = "/photos/default.jpg"

    # --- Xử lý trạng thái làm việc ---
    if employee.get("TrangThai") == 1:
        employee["TrangThaiText"] = "Đang làm việc"
        employee["TrangThaiClass"] = "success"
        employee["TrangThaiIcon"] = "fa-circle-check"
    else:
        employee["TrangThaiText"] = "Ngừng làm việc"
        employee["TrangThaiClass"] = "secondary"
        employee["TrangThaiIcon"] = "fa-pause-circle"

    # --- Ghi log xem chi tiết ---
    cursor.execute("""
        INSERT INTO LichSuThayDoi
            (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
        VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
    """, (
        "NhanVien",
        ma_nv,
        "Xem chi tiết",
        "Toàn bộ dòng",
        None,
        employee["HoTen"],
        session.get("username", "admin")
    ))

    conn.commit()
    conn.close()

    # --- Trả về trang hiển thị ---
    return render_template("employee_detail.html", employee=employee)

# Route thêm nhân viên

@app.route("/employees/add", methods=["GET", "POST"])
@require_role("admin")
def add_employee_web():
    departments = get_phongbans()

    if request.method == "POST":
        HoTen = request.form["HoTen"]
        Email = request.form["Email"]
        SDT = request.form.get("SDT")
        GioiTinh = int(request.form.get("GioiTinh", 1))
        NgaySinh = request.form.get("NgaySinh")
        MaPB = request.form["MaPB"]
        DiaChi = request.form.get("DiaChi")
        ChucVu = request.form.get("ChucVu")

        try:
            # --- Kết nối DB ---
            conn = get_sql_connection()
            cursor = conn.cursor()

            # --- Sinh mã nhân viên ---
            cursor.execute("SELECT MaNV FROM NhanVien WHERE MaPB=? ORDER BY MaNV DESC", (MaPB,))
            row = cursor.fetchone()
            if row and row[0]:
                num_part = ''.join([c for c in row[0] if c.isdigit()])
                next_num = int(num_part[-1]) + 1 if num_part else 1
            else:
                next_num = 1
            MaNV = f"NV{MaPB.upper()}{next_num}"

            # --- Kiểm tra trùng ---
            cursor.execute("SELECT COUNT(*) FROM NhanVien WHERE MaNV=?", (MaNV,))
            if cursor.fetchone()[0] > 0:
                flash(f"Mã nhân viên {MaNV} đã tồn tại!", "error")
                conn.close()
                return redirect(url_for("employee_list"))

            # --- Thêm nhân viên ---
            cursor.execute("""
                INSERT INTO NhanVien (MaNV, HoTen, Email, SDT, GioiTinh, NgaySinh, MaPB, DiaChi, ChucVu, TrangThai, NgayTao)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, GETDATE())
            """, (MaNV, HoTen, Email, SDT, GioiTinh, NgaySinh, MaPB, DiaChi, ChucVu))
            conn.commit()
            conn.close()
            print(f"✅ Đã thêm nhân viên {MaNV} vào bảng NhanVien.")

# --- Ghi lịch sử ---
            conn = get_sql_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO LichSuThayDoi 
                    (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "NhanVien",
                MaNV,
                "THÊM",
                "Toàn bộ dòng",
                None,
                f"Họ tên={HoTen}, Email={Email}, Chức vụ={ChucVu}, Phòng ban={MaPB}",
                session.get("username", "admin")
            ))
            conn.commit()
            conn.close()


            # --- Nhận ảnh từ client ---
            image_data = request.form.get("face_image")
            image_path = None

            if image_data:
                print("🖼️ Nhận ảnh base64 từ trình duyệt, đang lưu...")
                try:
                    image_data = image_data.split(",")[1]
                    image_bytes = base64.b64decode(image_data)

                    save_dir = os.path.join("static", "faces")
                    os.makedirs(save_dir, exist_ok=True)
                    image_path = os.path.join(save_dir, f"{MaNV}.jpg")

                    with open(image_path, "wb") as f:
                        f.write(image_bytes)

                    # --- Ghi DB ---
                    conn = get_sql_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO KhuonMat (MaNV, DuongDanAnh, TrangThai, NgayDangKy, MoTa)
                        VALUES (?, ?, 1, GETDATE(), ?)
                    """, (MaNV, image_path, "Ảnh chụp từ trình duyệt khi thêm nhân viên"))
                    conn.commit()
                    conn.close()
                    flash("✅ Đã thêm nhân viên và lưu ảnh khuôn mặt (từ trình duyệt)!", "success")

                except Exception as e:
                    print(f"⚠️ Lỗi khi lưu ảnh client: {e}")
                    flash("⚠️ Lưu ảnh khuôn mặt thất bại (client)!", "warning")

            else:
                # --- Nếu không có ảnh client, fallback sang OpenCV ---
                print("📸 Không có ảnh từ trình duyệt → thử chụp bằng camera server...")
                image_path = capture_photo_and_save(MaNV)
                if image_path:
                    flash("✅ Đã chụp và lưu ảnh khuôn mặt (server)!", "success")
                else:
                    flash("⚠️ Không nhận được ảnh khuôn mặt nào!", "warning")

            return redirect(url_for("employee_list"))

        except Exception as e:
            print(f"❌ Lỗi khi thêm nhân viên: {e}")
            flash("❌ Lỗi khi thêm nhân viên. Vui lòng thử lại!", "error")
            if 'conn' in locals():
                conn.close()
            return redirect(url_for("employee_list"))

    # Nếu GET → render form thêm
    return render_template("add_employee.html", departments=departments)

# --- Xóa mềm 1 nhân viên ---
@app.route("/employees/delete/<ma_nv>")
@require_role("admin")
def delete_employee_web(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT HoTen FROM NhanVien WHERE MaNV = ?", (ma_nv,))
        row = cursor.fetchone()
        old_name = row[0] if row else "(Không tìm thấy)"

        # Đánh dấu xóa mềm
        cursor.execute("""
            UPDATE NhanVien
            SET TrangThai = 0, NgayCapNhat = GETDATE()
            WHERE MaNV = ?
        """, (ma_nv,))

        # Vô hiệu hóa tài khoản
        cursor.execute("UPDATE TaiKhoan SET TrangThai = 0 WHERE MaNV = ?", (ma_nv,))

        # Ghi log
        cursor.execute("""
            INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                                       GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("NhanVien", ma_nv, "Xóa mềm", "TrangThai", 1, 0, session.get("user_id")))

        conn.commit()
        flash(f"✅ Đã ẩn (xóa mềm) nhân viên {old_name} ({ma_nv}).", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa mềm nhân viên: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("employee_list"))


# --- Xóa mềm nhiều nhân viên ---
@app.route("/employees/delete_selected", methods=["POST"])
@require_role("admin")
def delete_selected_employees():
    selected_ids = request.form.getlist("selected_employees")
    if not selected_ids:
        flash("⚠️ Chưa chọn nhân viên nào để xóa!", "warning")
        return redirect(url_for("employee_list"))

    conn = get_sql_connection()
    cursor = conn.cursor()

    skipped = []  # lưu danh sách nhân viên không thể xóa
    deleted = []  # lưu danh sách đã xóa

    try:
        for ma_nv in selected_ids:
            # ✅ Kiểm tra nhân viên có đang là quản lý phòng ban không
            cursor.execute("SELECT MaPB FROM PhongBan WHERE QuanLyPB = ?", (ma_nv,))
            pb_row = cursor.fetchone()
            if pb_row:
                skipped.append(ma_nv)
                continue  # bỏ qua không xóa

            # ✅ Xóa mềm nhân viên (TrangThai = 0)
            cursor.execute("""
                UPDATE NhanVien 
                SET TrangThai = 0, NgayCapNhat = GETDATE()
                WHERE MaNV = ?
            """, (ma_nv,))
            cursor.execute("UPDATE TaiKhoan SET TrangThai = 0 WHERE MaNV = ?", (ma_nv,))

            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, ("NhanVien", ma_nv, "Xóa mềm", "TrangThai", 1, 0, session.get("user_id")))

            deleted.append(ma_nv)

        conn.commit()

        # ✅ Hiển thị kết quả
        msg = ""
        if deleted:
            msg += f"🗑 Đã xóa mềm {len(deleted)} nhân viên thành công. "
        if skipped:
            msg += f"⚠️ {len(skipped)} nhân viên đang là quản lý, không thể xóa."
        flash(msg.strip(), "info" if skipped else "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa nhiều nhân viên: {e}", "danger")

    finally:
        conn.close()

    return redirect(url_for("employee_list"))

# ============================================================
# 🔹 DANH SÁCH NHÂN VIÊN ĐÃ XÓA
# ============================================================
@app.route("/employees/deleted")
@require_role("admin")
def employee_list_deleted():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # 🧩 Lấy danh sách nhân viên đã xóa (TrangThai = 0) + ảnh khuôn mặt
        cursor.execute("""
            SELECT 
                nv.MaNV, 
                nv.HoTen, 
                nv.Email, 
                nv.SDT, 
                nv.ChucVu, 
                pb.TenPB, 
                ql.HoTen AS TenQuanLy,       -- ✅ Lấy tên người quản lý từ QuanLyPB
                nv.NgayCapNhat,
                k.DuongDanAnh
            FROM NhanVien nv
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            LEFT JOIN NhanVien ql ON pb.QuanLyPB = ql.MaNV  -- ✅ đúng cột hiện có
            LEFT JOIN KhuonMat k ON nv.MaNV = k.MaNV
            WHERE nv.TrangThai = 0
            ORDER BY nv.NgayCapNhat DESC
        """)
        deleted_employees = cursor.fetchall()

        # 🏢 Lấy danh sách phòng ban đã xóa (TrangThai = 0)
        cursor.execute("""
            SELECT 
                pb.MaPB, 
                pb.TenPB, 
                ql.HoTen AS TenQuanLy, 
                pb.NgayTao
            FROM PhongBan pb
            LEFT JOIN NhanVien ql ON pb.QuanLyPB = ql.MaNV
            WHERE pb.TrangThai = 0
            ORDER BY pb.NgayTao DESC
        """)
        deleted_departments = cursor.fetchall()

    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách đã xóa: {str(e)}", "danger")
        deleted_employees, deleted_departments = [], []

    finally:
        conn.close()

    # ✅ Trả về giao diện
    return render_template(
        "deleted_records.html",
        deleted_employees=deleted_employees,
        deleted_departments=deleted_departments,
        active_tab="employees"  # tab nhân viên mở mặc định
    )


# --- Khôi phục nhân viên ---
@app.route("/employees/restore/<ma_nv>")
@require_role("admin")
def restore_employee(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE NhanVien
            SET TrangThai = 1, NgayCapNhat = GETDATE()
            WHERE MaNV = ?
        """, (ma_nv,))
        cursor.execute("UPDATE TaiKhoan SET TrangThai = 1 WHERE MaNV = ?", (ma_nv,))

        cursor.execute("""
            INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                                       GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("NhanVien", ma_nv, "Khôi phục", "TrangThai", 0, 1, session.get("user_id")))

        conn.commit()
        flash(f"♻️ Đã khôi phục nhân viên {ma_nv} thành công.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục nhân viên: {e}", "danger")
    finally:
        conn.close()

    # ✅ Dùng giao diện gộp
    return redirect(url_for("employee_list_deleted"))

# --- Khôi phục nhiều nhân viên ---
@app.route("/employees/restore_selected", methods=["POST"])
@require_role("admin")
def restore_selected_employees():
    selected_ids = request.form.getlist("selected_employees")
    if not selected_ids:
        flash("⚠️ Chưa chọn nhân viên nào để khôi phục!", "warning")
        return redirect(url_for("employee_list_deleted"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    try:
        for ma_nv in selected_ids:
            cursor.execute("UPDATE NhanVien SET TrangThai = 1, NgayCapNhat = GETDATE() WHERE MaNV = ?", (ma_nv,))
            cursor.execute("UPDATE TaiKhoan SET TrangThai = 1 WHERE MaNV = ?", (ma_nv,))
            cursor.execute("""
                INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                                           GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, ("NhanVien", ma_nv, "Khôi phục", "TrangThai", 0, 1, session.get("user_id")))
        conn.commit()
        flash(f"♻️ Đã khôi phục {len(selected_ids)} nhân viên thành công.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục nhiều nhân viên: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("employee_list_deleted"))


# Route chỉnh sửa nhân viên
@app.route("/employees/edit/<ma_nv>", methods=["GET", "POST"], endpoint="edit_employee_web")
@require_role("admin")
def edit_employee_web(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy thông tin nhân viên ---
    cursor.execute("""
        SELECT nv.MaNV, nv.MaHienThi, nv.HoTen, nv.Email, nv.SDT, nv.GioiTinh, nv.NgaySinh, nv.DiaChi,
               nv.MaPB, nv.ChucVu, nv.TrangThai, pb.TenPB, km.DuongDanAnh
        FROM NhanVien nv
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat km ON nv.MaNV = km.MaNV
        WHERE nv.MaNV = ?
    """, (ma_nv,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash(f"❌ Không tìm thấy nhân viên {ma_nv}", "error")
        return redirect(url_for("employee_list"))

    columns = [col[0] for col in cursor.description]
    employee = dict(zip(columns, row))

    # Ảnh đại diện
    avatar = employee.get("DuongDanAnh")
    if avatar and avatar.strip():
        avatar = avatar.replace("\\", "/")
        if not avatar.startswith("/"):
            avatar = f"/{avatar}"
        employee["AnhDaiDien"] = avatar
    else:
        employee["AnhDaiDien"] = "/photos/default.jpg"

    # Danh sách phòng ban
    cursor.execute("SELECT MaPB, TenPB FROM PhongBan")
    departments = [dict(zip([c[0] for c in cursor.description], r)) for r in cursor.fetchall()]
    conn.close()

    # Nếu người dùng cập nhật
    if request.method == "POST":
        hoten = request.form.get("HoTen", "").strip()
        email = request.form.get("Email", "").strip()
        sdt = request.form.get("SDT", "").strip()
        ngaysinh = request.form.get("NgaySinh", "").strip() or None
        diachi = request.form.get("DiaChi", "").strip()
        ma_pb_moi = request.form.get("MaPB", "").strip()
        chucvu = request.form.get("ChucVu", "").strip()

        gioitinh = 1 if request.form.get("GioiTinh", "").lower() in ["1", "nam", "true"] else 0
        trangthai = 1 if request.form.get("TrangThai", "").lower() in ["1", "hoạt động", "active", "true"] else 0

        file = request.files.get("avatar")
        user_id = session.get("user_id", "Hệ thống")

        conn = get_sql_connection()
        cursor = conn.cursor()

        # Lấy phòng ban và mã hiển thị hiện tại
        cursor.execute("SELECT MaPB, MaHienThi FROM NhanVien WHERE MaNV=?", (ma_nv,))
        row = cursor.fetchone()
        old_pb = row[0] if row else None
        old_ma_hienthi = row[1] if row else None

        # 🟦 Nếu đổi phòng ban → sinh MaHienThi mới theo MaHienThi của PhongBan
        if ma_pb_moi != old_pb:
            # Lấy mã hiển thị của phòng ban (ví dụ: KD, TC, NS, MT, M)
            cursor.execute("SELECT MaHienThi FROM PhongBan WHERE MaPB=?", (ma_pb_moi,))
            row = cursor.fetchone()
            pb_short = None
            if row and row[0]:
                pb_short = row[0].strip().upper()
            else:
                print(f"⚠️ Không tìm thấy MaHienThi của phòng ban {ma_pb_moi}, fallback về 2 ký tự cuối.")
                pb_short = ma_pb_moi[-2:].upper()

            # Kiểm tra độ dài — nếu quá ngắn, thêm chữ X để tránh lỗi
            if len(pb_short) < 1:
                pb_short = "XX"

            # Tìm mã hiển thị cao nhất trong phòng ban đó
            cursor.execute("""
                SELECT TOP 1 MaHienThi FROM NhanVien 
                WHERE MaPB=? AND MaHienThi LIKE ?
                ORDER BY MaHienThi DESC
            """, (ma_pb_moi, f"NV{pb_short}%"))
            row = cursor.fetchone()
            if row and row[0]:
                num_part = ''.join([c for c in row[0] if c.isdigit()])
                next_num = int(num_part) + 1 if num_part else 1
            else:
                next_num = 1

            # Ghép mã hiển thị mới
            new_ma_hienthi = f"NV{pb_short}{next_num}"

            # Cập nhật nhân viên
            cursor.execute("""
    UPDATE NhanVien
    SET HoTen=?, Email=?, SDT=?, GioiTinh=?, NgaySinh=?, DiaChi=?, 
        MaPB=?, ChucVu=?, TrangThai=?, NgayCapNhat=GETDATE()
    WHERE MaNV=?
""", (hoten, email, sdt, gioitinh, ngaysinh, diachi,
      ma_pb_moi, chucvu, trangthai, ma_nv))


            # Ghi log thay đổi
            cursor.execute("""
                INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, NguoiThucHien)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ("NhanVien", ma_nv, "Sửa", "MaPB", old_pb, ma_pb_moi, user_id))
            cursor.execute("""
                INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, NguoiThucHien)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ("NhanVien", ma_nv, "Sửa", "MaHienThi", old_ma_hienthi, new_ma_hienthi, user_id))

        else:
            # 🔹 Không đổi phòng ban → chỉ cập nhật thông tin
            cursor.execute("""
                UPDATE NhanVien
                SET HoTen=?, Email=?, SDT=?, GioiTinh=?, NgaySinh=?, DiaChi=?, 
                    MaPB=?, ChucVu=?, TrangThai=?
                WHERE MaNV=?
            """, (hoten, email, sdt, gioitinh, ngaysinh, diachi,
                  ma_pb_moi, chucvu, trangthai, ma_nv))
            new_ma_hienthi = old_ma_hienthi

        # Ảnh đại diện
        if file and file.filename != "":
            os.makedirs("photos", exist_ok=True)
            filename = f"{new_ma_hienthi}.jpg"
            save_path = os.path.join("photos", filename)
            file.save(save_path)
            db_path = f"photos/{filename}"

            cursor.execute("SELECT COUNT(*) FROM KhuonMat WHERE MaNV=?", (ma_nv,))
            exists = cursor.fetchone()[0]
            if exists:
                cursor.execute("UPDATE KhuonMat SET DuongDanAnh=? WHERE MaNV=?", (db_path, ma_nv))
            else:
                cursor.execute("INSERT INTO KhuonMat (MaNV, DuongDanAnh, TrangThai) VALUES (?, ?, 1)",
                               (ma_nv, db_path))

            cursor.execute("""
                INSERT INTO LichSuThayDoi
                (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriMoi, NguoiThucHien)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("KhuonMat", ma_nv, "Cập nhật", "DuongDanAnh", db_path, user_id))

        conn.commit()
        conn.close()

        flash("✅ Cập nhật thông tin nhân viên thành công!", "success")
        return redirect(url_for("employee_detail", ma_nv=ma_nv))

    return render_template("edit_employee.html", employee=employee, departments=departments)

@app.route("/deleted_records")
@require_role("admin")
def deleted_data():
    tab = request.args.get("tab", "employees")  # tab mặc định
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # =====================================================
        # 🧍‍♂️ NHÂN VIÊN
        # =====================================================
        if tab == "employees":
            cursor.execute("""
                SELECT nv.MaNV, nv.HoTen, nv.Email, nv.ChucVu, pb.TenPB
                FROM NhanVien nv
                LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
                WHERE nv.TrangThai = 0
            """)
            deleted_employees = cursor.fetchall()
            return render_template(
                "deleted_records.html",
                active_tab="employees",
                deleted_employees=deleted_employees
            )

        # =====================================================
        # 🏢 PHÒNG BAN
        # =====================================================
        elif tab == "departments":
            cursor.execute("""
                SELECT pb.MaPB, pb.TenPB, pb.QuanLy, 
                       (SELECT COUNT(*) FROM NhanVien WHERE MaPB = pb.MaPB) AS SoNhanVien
                FROM PhongBan pb
                WHERE pb.TrangThai = 0
            """)
            deleted_departments = cursor.fetchall()
            return render_template(
                "deleted_records.html",
                active_tab="departments",
                deleted_departments=deleted_departments
            )

        # =====================================================
        # 🔐 TÀI KHOẢN
        # =====================================================
        elif tab == "accounts":
            cursor.execute("""
                SELECT t.MaTK, t.TenDangNhap, ISNULL(n.HoTen, N'—') AS HoTen, 
                       t.VaiTro, t.NgayTao
                FROM TaiKhoan t
                LEFT JOIN NhanVien n ON t.MaNV = n.MaNV
                WHERE t.TrangThai = 0
            """)
            deleted_accounts = cursor.fetchall()
            return render_template(
                "deleted_records.html",
                active_tab="accounts",
                deleted_accounts=deleted_accounts
            )

                # =====================================================
        # 🕓 CHẤM CÔNG (đã chỉnh chuẩn theo bản /attendance/deleted)
        # =====================================================
        elif tab == "attendance":
            from datetime import datetime, time

            # Lấy dữ liệu chấm công
            cursor.execute("""
                SELECT 
                    cc.MaChamCong,
                    ISNULL(cc.MaNV, nv.MaNV) AS MaNV,
                    nv.HoTen,
                    pb.TenPB,
                    clv.TenCa,
                    cc.NgayChamCong,
                    cc.GioVao,
                    cc.GioRa,
                    cc.TrangThai

                FROM ChamCong cc
                JOIN NhanVien nv ON cc.MaNV = nv.MaNV
                LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
                LEFT JOIN CaLamViec clv ON cc.MaCa = clv.MaCa
                WHERE cc.DaXoa = 0
                ORDER BY cc.NgayChamCong DESC
            """)
            rows = cursor.fetchall()

            # ✅ Hàm format giờ (chỉ lấy HH:MM:SS, bỏ ngày 1900)
            def format_time(value):
                if not value:
                    return "—"
                if isinstance(value, (datetime, time)):
                    return value.strftime("%H:%M:%S")
                val = str(value)
                if " " in val:
                    val = val.split(" ")[-1]
                if "1900" in val:
                    val = val.replace("1900-01-01", "").strip()
                return val or "—"

            deleted_attendance = []
            for row in rows:
                ma_cham_cong, ma_nv, ho_ten, ten_pb, ten_ca, ngay, gio_vao, gio_ra, trang_thai = row

                gio_vao_txt = format_time(gio_vao)
                gio_ra_txt = format_time(gio_ra)

                trang_thai = int(trang_thai) if trang_thai is not None else -1
                if trang_thai == 1:
                    status_text, status_class = "Đúng giờ", "bg-success"
                elif trang_thai == 2:
                    status_text, status_class = "Đi muộn", "bg-warning text-dark"
                elif trang_thai == 0:
                    status_text, status_class = "Vắng", "bg-danger"
                else:
                    status_text, status_class = "Không xác định", "bg-secondary"

                deleted_attendance.append({
                    "MaChamCong": str(ma_cham_cong).strip(),
                    "MaNV": str(ma_nv).strip() if ma_nv else "—",
                    "HoTen": ho_ten or "",
                    "TenPB": ten_pb or "",
                    "TenCa": ten_ca or "",
                    "NgayChamCong": (
                        ngay.strftime("%Y-%m-%d") if isinstance(ngay, datetime)
                        else str(ngay)[:10] if ngay else ""
                    ),
                    "GioVao": gio_vao_txt,
                    "GioRa": gio_ra_txt,
                    "TrangThai": trang_thai,
                    "TrangThaiText": status_text,
                    "StatusClass": status_class
                })

            # ✅ Render đúng tab
            return render_template(
                "deleted_records.html",
                active_tab="attendance",
                deleted_attendance=deleted_attendance
            )


        # =====================================================
        # 😃 KHUÔN MẶT
        # =====================================================
        elif tab == "faces":
            cursor.execute("""
                SELECT 
                    k.FaceID,
                    k.MaNV,
                    nv.HoTen,
                    pb.TenPB,
                    k.DuongDanAnh,
                    k.NgayDangKy,
                    k.TrangThai,
                    k.MoTa
                FROM KhuonMat k
                JOIN NhanVien nv ON k.MaNV = nv.MaNV
                LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
                WHERE nv.TrangThai = 0 OR k.TrangThai = 0
                ORDER BY k.NgayDangKy DESC
            """)
            deleted_faces = cursor.fetchall()
            return render_template(
                "deleted_records.html",
                active_tab="faces",
                deleted_faces=deleted_faces
            )

        # =====================================================
        # 🚨 TRƯỜNG HỢP KHÁC
        # =====================================================
        else:
            flash("⚠️ Tab không hợp lệ, đã chuyển về Nhân viên!", "warning")
            return redirect(url_for("deleted_data", tab="employees"))

    except Exception as e:
        flash(f"❌ Lỗi khi tải dữ liệu đã xóa: {e}", "error")
        return redirect(url_for("admin_dashboard"))

    finally:
        conn.close()

# QUẢN LÝ PHÒNG BAN

# ============================================================
# 🔹 DANH SÁCH PHÒNG BAN (chỉ phòng đang hoạt động)
# ============================================================
@app.route("/departments")
@require_role("admin")
def departments():
    conn = get_sql_connection()
    cursor = conn.cursor()
    keyword = request.args.get("q", "").strip()

    # --- Lấy danh sách phòng ban đang hoạt động + tên người quản lý ---
    query = """
        SELECT 
            pb.MaPB, 
            pb.TenPB, 
            nv.HoTen AS TenQuanLy, 
            pb.TrangThai, 
            COUNT(nv2.MaNV) AS SoNhanVien
        FROM PhongBan pb
        LEFT JOIN NhanVien nv ON pb.QuanLyPB = nv.MaNV        -- ✅ Tên quản lý
        LEFT JOIN NhanVien nv2 ON pb.MaPB = nv2.MaPB           -- ✅ Đếm nhân viên
        WHERE pb.TrangThai = 1                                 -- ✅ Chỉ lấy phòng đang hoạt động
    """

    params = ()
    if keyword:
        query += " AND (pb.TenPB LIKE ? OR pb.MaPB LIKE ?)"
        params = (f"%{keyword}%", f"%{keyword}%")

    query += """
        GROUP BY pb.MaPB, pb.TenPB, nv.HoTen, pb.TrangThai
        ORDER BY pb.MaPB
    """
    cursor.execute(query, params)
    rows = cursor.fetchall()

    # --- Chuẩn bị dữ liệu render ---
    departments = []
    for row in rows:
        ma_pb, ten_pb, ten_quan_ly, trang_thai, so_nv = row
        departments.append({
            "ma_pb": ma_pb,
            "ten_pb": ten_pb,
            "so_nv": so_nv,
            "manager": ten_quan_ly if ten_quan_ly else "Chưa có",
            "trang_thai": "Đang hoạt động",
            "last_updated": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        })

    # --- Thống kê (chỉ đếm phòng hoạt động) ---
    cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE TrangThai = 1")
    active_departments = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE TrangThai = 1")
    total_departments = cursor.fetchone()[0]  # ✅ Tổng cũng chỉ tính phòng hoạt động

    cursor.execute("""
        SELECT COUNT(*) 
        FROM NhanVien nv
        JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        WHERE nv.TrangThai = 1 AND pb.TrangThai = 1
    """)
    total_employees = cursor.fetchone()[0]  # ✅ Chỉ đếm nhân viên thuộc phòng hoạt động

    conn.close()

    # --- Render ---
    return render_template(
        "departments.html",
        departments=departments,
        keyword=keyword,
        total_departments=total_departments,
        total_employees=total_employees,
        active_departments=active_departments
    )


# ============================================================
# 🔹 CHI TIẾT PHÒNG BAN (chỉ cho phép xem nếu đang hoạt động)
# ============================================================
@app.route("/departments/<ma_pb>")
@require_role("admin")
def department_detail(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy thông tin phòng ban (chỉ hoạt động) ---
    cursor.execute("""
        SELECT 
            pb.MaPB, 
            pb.TenPB, 
            nv.HoTen AS TenQuanLy, 
            pb.TrangThai, 
            pb.MoTa
        FROM PhongBan pb
        LEFT JOIN NhanVien nv ON pb.QuanLyPB = nv.MaNV
        WHERE pb.MaPB = ? AND pb.TrangThai = 1
    """, (ma_pb,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("❌ Phòng ban này không tồn tại hoặc đã ngừng hoạt động!", "error")
        return redirect(url_for("departments"))

    ma_pb, ten_pb, ten_quan_ly, trang_thai, mo_ta = row
    pb_info = {
        "ma_pb": ma_pb,
        "ten_pb": ten_pb,
        "quan_ly": ten_quan_ly if ten_quan_ly else "Chưa có",
        "trang_thai": "Đang hoạt động",
        "mo_ta": mo_ta if mo_ta else "Không có mô tả"
    }

    # --- Ghi log xem chi tiết ---
    try:
        username = session.get("username") or session.get("user_id") or "admin"
        cursor.execute("EXEC sys.sp_set_session_context @key=N'user', @value=?", (username,))
        cursor.execute("""
            INSERT INTO LichSuThayDoi
            (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, (
            "PhongBan",
            ma_pb,
            "Xem chi tiết",
            "Toàn bộ dòng",
            None,
            pb_info["ten_pb"],
            username
        ))
        conn.commit()
    except Exception as e:
        print("⚠️ Lỗi ghi log xem chi tiết phòng ban:", e)

    # --- Lấy danh sách nhân viên trong phòng ban hoạt động ---
    keyword = request.args.get("q", "").strip()
    order = request.args.get("sort", "ten")

    query = """
        SELECT MaNV, HoTen, ChucVu, NgayVaoLam
        FROM NhanVien
        WHERE MaPB = ? AND TrangThai = 1
    """
    params = [ma_pb]
    if keyword:
        query += " AND (HoTen LIKE ? OR MaNV LIKE ? OR ChucVu LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

    if order == "ten":
        query += " ORDER BY HoTen"
    elif order == "chucvu":
        query += " ORDER BY ChucVu"
    else:
        query += " ORDER BY MaNV"

    cursor.execute(query, params)
    nhanviens = cursor.fetchall()

    conn.close()

    return render_template(
        "department_detail.html",
        pb=pb_info,
        nhanviens=nhanviens,
        keyword=keyword,
        order=order
    )

@app.route("/departments/my")
@require_role("manager")
def my_department():
    ma_nv = session.get("ma_nv")
    conn = get_sql_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT MaPB FROM PhongBan WHERE QuanLyPB = ?
    """, (ma_nv,))
    ma_pb = cursor.fetchone()
    if not ma_pb:
        flash("Bạn chưa được chỉ định làm quản lý phòng ban nào!", "info")
        return redirect(url_for("home"))
    return redirect(url_for("department_detail", ma_pb=ma_pb[0]))


#thêm phòng ban
@app.route("/departments/add", methods=["GET", "POST"])
@require_role("admin")
def add_department():
    if request.method == "POST":
        ten_pb = request.form["ten_pb"].strip()
        mo_ta = request.form.get("mo_ta", "").strip()

        if not ten_pb:
            flash("Tên phòng ban không được để trống!", "error")
            return redirect(url_for("add_department"))

        # Tạo mã viết tắt từ tên phòng ban
        # Ví dụ: "Công nghệ thông tin" -> "CNTT"
        words = ten_pb.split()
        ma_pb_base = "".join(w[0].upper() for w in words if w)
        ma_pb = ma_pb_base

        conn = get_sql_connection()
        cursor = conn.cursor()

        # Nếu mã bị trùng, thêm số tăng dần phía sau: KD1, KD2, ...
        i = 1
        while True:
            cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE MaPB = ?", (ma_pb,))
            count = cursor.fetchone()[0]
            if count == 0:
                break
            ma_pb = f"{ma_pb_base}{i}"
            i += 1

        ngay_tao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trang_thai = 1  # 1 = hoạt động

        # Thêm phòng ban vào database
        cursor.execute(
            "INSERT INTO PhongBan (MaPB, TenPB, MoTa, NgayTao, TrangThai) VALUES (?, ?, ?, ?, ?)",
            (ma_pb, ten_pb, mo_ta, ngay_tao, trang_thai)
        )
        conn.commit()
        conn.close()

        flash(f"Thêm phòng ban '{ten_pb}' (Mã: {ma_pb}) thành công!", "success")
        return redirect(url_for("departments"))

    return render_template("add_department.html")
# --- Chỉnh sửa phòng ban ---
@app.route("/departments/edit/<ma_pb>", methods=["GET", "POST"])
@require_role("admin")
def edit_department(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # Lấy dữ liệu phòng ban cũ
    cursor.execute("SELECT MaPB, TenPB, MoTa, TrangThai FROM PhongBan WHERE MaPB = ?", (ma_pb,))
    department = cursor.fetchone()

    if not department:
        flash("Không tìm thấy phòng ban!", "danger")
        conn.close()
        return redirect(url_for("departments"))

    old_ma_pb, old_ten_pb, old_mo_ta, old_trang_thai = department

    if request.method == "POST":
        ten_pb = request.form["ten_pb"].strip()
        mo_ta = request.form["mo_ta"].strip()
        trang_thai = 1 if request.form.get("trang_thai") == "on" else 0

        # Hàm tạo mã viết tắt từ tên phòng ban
        def tao_ma_viet_tat(ten):
            parts = ten.strip().split()
            if len(parts) == 1:
                return parts[0][:2].upper()
            else:
                return "".join(word[0].upper() for word in parts)

        new_ma_pb = tao_ma_viet_tat(ten_pb)

        try:
            # Nếu chỉ đổi mô tả/trạng thái, không đổi tên
            if ten_pb == old_ten_pb:
                cursor.execute("""
                    UPDATE PhongBan
                    SET MoTa = ?, TrangThai = ?
                    WHERE MaPB = ?
                """, (mo_ta, trang_thai, old_ma_pb))
                conn.commit()
                flash("Cập nhật mô tả phòng ban thành công!", "success")

            else:
                # Kiểm tra trùng mã phòng ban
                cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE MaPB = ?", (new_ma_pb,))
                if cursor.fetchone()[0] > 0:
                    flash(f"Mã phòng ban '{new_ma_pb}' đã tồn tại! Vui lòng chọn tên khác.", "danger")
                    conn.close()
                    return redirect(url_for("departments"))

                #  Tạo phòng ban mới
                cursor.execute("""
                    INSERT INTO PhongBan (MaPB, TenPB, MoTa, TrangThai)
                    VALUES (?, ?, ?, ?)
                """, (new_ma_pb, ten_pb, mo_ta, trang_thai))

                # Lấy danh sách nhân viên thuộc phòng ban cũ
                cursor.execute("SELECT MaNV FROM NhanVien WHERE MaPB = ?", (old_ma_pb,))
                old_nv_list = [row[0] for row in cursor.fetchall()]

                # Tắt toàn bộ ràng buộc FK liên quan đến MaNV
                cursor.execute("ALTER TABLE TaiKhoan NOCHECK CONSTRAINT FK_TaiKhoan_NhanVien")
                cursor.execute("ALTER TABLE KhuonMat NOCHECK CONSTRAINT FK__KhuonMat__MaNV__4222D4EF")
                cursor.execute("ALTER TABLE ChamCong NOCHECK CONSTRAINT FK__ChamCong__MaNV__4F7CD00D")
                cursor.execute("ALTER TABLE LichLamViec NOCHECK CONSTRAINT FK__LichLamVie__MaNV__4AB81AF0")

                # Cập nhật mã nhân viên và đồng bộ sang các bảng liên quan
                for old_nv in old_nv_list:
                    so_thu_tu = ''.join(ch for ch in old_nv if ch.isdigit())
                    new_nv = f"NV{new_ma_pb}{so_thu_tu}"

                    # NhanVien
                    cursor.execute("""
                        UPDATE NhanVien
                        SET MaNV = ?, MaPB = ?
                        WHERE MaNV = ?
                    """, (new_nv, new_ma_pb, old_nv))

                    # TaiKhoan
                    # TaiKhoan – chỉ cập nhật cho nhân viên (không chạm admin)
                    cursor.execute("""
                        UPDATE TaiKhoan
                        SET MaNV = ?, TenDangNhap = ?
                        WHERE MaNV = ? AND VaiTro = 'nhanvien'
                    """, (new_nv, new_nv, old_nv))


                    # KhuonMat
                    cursor.execute("""
                        UPDATE KhuonMat
                        SET MaNV = ?
                        WHERE MaNV = ?
                    """, (new_nv, old_nv))

                    # ChamCong
                    cursor.execute("""
                        UPDATE ChamCong
                        SET MaNV = ?
                        WHERE MaNV = ?
                    """, (new_nv, old_nv))

                    # LichLamViec
                    cursor.execute("""
                        UPDATE LichLamViec
                        SET MaNV = ?
                        WHERE MaNV = ?
                    """, (new_nv, old_nv))

                # Bật lại các ràng buộc FK
                cursor.execute("ALTER TABLE TaiKhoan WITH CHECK CHECK CONSTRAINT FK_TaiKhoan_NhanVien")
                cursor.execute("ALTER TABLE KhuonMat WITH CHECK CHECK CONSTRAINT FK__KhuonMat__MaNV__4222D4EF")
                cursor.execute("ALTER TABLE ChamCong WITH CHECK CHECK CONSTRAINT FK__ChamCong__MaNV__4F7CD00D")
                cursor.execute("ALTER TABLE LichLamViec WITH CHECK CHECK CONSTRAINT FK__LichLamVie__MaNV__4AB81AF0")

                # Xóa phòng ban cũ
                cursor.execute("DELETE FROM PhongBan WHERE MaPB = ?", (old_ma_pb,))

                conn.commit()
                flash(f"Đã đổi '{old_ten_pb}' → '{ten_pb}' (mã mới: {new_ma_pb}) và đồng bộ toàn bộ dữ liệu nhân viên, tài khoản, khuôn mặt, chấm công, lịch làm việc thành công!", "success")

        except Exception as e:
            conn.rollback()
            flash(f"Lỗi khi cập nhật phòng ban: {e}", "danger")

        finally:
            conn.close()

        return redirect(url_for("departments"))

    conn.close()
    return render_template("edit_department.html", department=department)

# ============================================================
# 🔹 XÓA MỀM 1 PHÒNG BAN
# ============================================================
@app.route("/departments/delete/<string:ma_pb>", methods=["POST"])
@require_role("admin")
def delete_department(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # ✅ Lấy thông tin để ghi log
        cursor.execute("SELECT TenPB, TrangThai FROM PhongBan WHERE MaPB = ?", (ma_pb,))
        row = cursor.fetchone()
        if not row:
            flash("❌ Không tìm thấy phòng ban để xóa!", "danger")
            return redirect(url_for("departments"))

        old_name, old_status = row

        # ✅ Xóa mềm: TrangThai = 0
        cursor.execute("""
            UPDATE PhongBan
            SET TrangThai = 0
            WHERE MaPB = ?
        """, (ma_pb,))

        # ✅ Ghi log
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, (
            "PhongBan",
            ma_pb,
            "Xóa mềm",
            "TrangThai",
            old_status,
            0,
            session.get("username", "Hệ thống")
        ))

        conn.commit()
        flash(f"🗑 Đã xóa mềm phòng ban {old_name} ({ma_pb}).", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa mềm phòng ban: {str(e)}", "danger")

    finally:
        conn.close()

    return redirect(url_for("departments"))


# ============================================================
# 🔹 XÓA MỀM NHIỀU PHÒNG BAN
# ============================================================
@app.route("/departments/delete-multiple", methods=["POST"])
@require_role("admin")
def delete_multiple_departments():
    selected_ids = request.form.getlist("selected_departments")

    if not selected_ids:
        flash("⚠️ Bạn chưa chọn phòng ban nào để xóa!", "warning")
        return redirect(url_for("departments"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for ma_pb in selected_ids:
            cursor.execute("SELECT TenPB, TrangThai FROM PhongBan WHERE MaPB = ?", (ma_pb,))
            row = cursor.fetchone()
            if not row:
                continue

            old_name, old_status = row

            # ✅ Xóa mềm
            cursor.execute("""
                UPDATE PhongBan
                SET TrangThai = 0
                WHERE MaPB = ?
            """, (ma_pb,))

            # ✅ Ghi log
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "PhongBan",
                ma_pb,
                "Xóa mềm nhiều",
                "TrangThai",
                old_status,
                0,
                username
            ))

        conn.commit()
        flash(f"🗑 Đã xóa mềm {len(selected_ids)} phòng ban thành công.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa nhiều phòng ban: {str(e)}", "danger")

    finally:
        conn.close()

    return redirect(url_for("departments"))

# ============================================================
# 🔹 KHÔI PHỤC 1 PHÒNG BAN (CHUẨN)
# ============================================================
@app.route("/departments/restore/<string:ma_pb>", methods=["POST"])
@require_role("admin")
def restore_department(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        print(f"🔄 Đang khôi phục phòng ban: {ma_pb}")

        # 🧩 Kiểm tra xem phòng ban có tồn tại và đang bị tắt không
        cursor.execute("""
            SELECT TenPB, TrangThai 
            FROM PhongBan 
            WHERE MaPB = ?
        """, (ma_pb,))
        row = cursor.fetchone()

        if not row:
            flash("❌ Không tìm thấy phòng ban cần khôi phục!", "danger")
            return redirect(url_for("deleted_departments_list"))

        ten_pb, trang_thai = row

        # 🟠 Nếu phòng ban đã hoạt động rồi thì không cần khôi phục
        if trang_thai == 1:
            flash(f"⚠️ Phòng ban {ten_pb} ({ma_pb}) đang hoạt động, không cần khôi phục.", "warning")
            return redirect(url_for("deleted_departments_list"))

        # ✅ Cập nhật trạng thái thành 1 (hoạt động)
        cursor.execute("""
            UPDATE PhongBan
            SET TrangThai = 1
            WHERE MaPB = ?
        """, (ma_pb,))

        # ✅ Ghi log hành động khôi phục
        username = session.get("username", "Hệ thống")
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, (
            "PhongBan",
            ma_pb,
            "Khôi phục",
            "TrangThai",
            trang_thai,
            1,
            username
        ))

        conn.commit()
        flash(f"♻️ Đã khôi phục phòng ban {ten_pb} ({ma_pb}) thành công.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục phòng ban: {str(e)}", "danger")

    finally:
        conn.close()

    # ✅ Quay lại danh sách phòng ban đã xóa
    return redirect(url_for("deleted_departments_list"))

# ============================================================
# 🔹 KHÔI PHỤC NHIỀU PHÒNG BAN
# ============================================================
@app.route("/departments/restore-multiple", methods=["POST"])
@require_role("admin")
def restore_multiple_departments():
    selected_ids = request.form.getlist("selected_departments")

    if not selected_ids:
        flash("⚠️ Chưa chọn phòng ban nào để khôi phục!", "warning")
        return redirect(url_for("deleted_departments_list"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for ma_pb in selected_ids:
            cursor.execute("""
                UPDATE PhongBan
                SET TrangThai = 1
                WHERE MaPB = ?
            """, (ma_pb,))

            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "PhongBan",
                ma_pb,
                "Khôi phục nhiều",
                "TrangThai",
                0,
                1,
                username
            ))

        conn.commit()
        flash(f"♻️ Đã khôi phục {len(selected_ids)} phòng ban thành công.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục nhiều phòng ban: {str(e)}", "danger")

    finally:
        conn.close()

    return redirect(url_for("deleted_departments_list"))

# ============================================================
# 🔹 DANH SÁCH PHÒNG BAN & NHÂN VIÊN ĐÃ XÓA (CÓ TÊN NGƯỜI QUẢN LÝ)
# ============================================================
@app.route("/departments/deleted")
@require_role("admin")
def deleted_departments_list():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # 🏢 Lấy danh sách phòng ban đã xóa (TrangThai = 0) + tên người quản lý
        cursor.execute("""
            SELECT 
                pb.MaPB, 
                pb.TenPB, 
                ql.HoTen AS TenQuanLy,       -- ✅ Lấy tên quản lý thật
                pb.NgayTao
            FROM PhongBan pb
            LEFT JOIN NhanVien ql ON pb.QuanLyPB = ql.MaNV  -- ✅ đúng cột hiện có
            WHERE pb.TrangThai = 0
            ORDER BY pb.NgayTao DESC
        """)
        deleted_departments = cursor.fetchall()

        # 👨‍💼 Lấy danh sách nhân viên đã xóa (TrangThai = 0)
        cursor.execute("""
            SELECT 
                nv.MaNV, 
                nv.HoTen, 
                nv.Email, 
                nv.SDT, 
                nv.ChucVu, 
                pb.TenPB, 
                nv.NgayCapNhat,
                ql.HoTen AS TenQuanLy
            FROM NhanVien nv
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            LEFT JOIN NhanVien ql ON pb.QuanLyPB = ql.MaNV  -- ✅ thêm để lấy quản lý phòng ban của nhân viên đó
            WHERE nv.TrangThai = 0
            ORDER BY nv.NgayCapNhat DESC
        """)
        deleted_employees = cursor.fetchall()

    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách đã xóa: {str(e)}", "danger")
        deleted_departments, deleted_employees = [], []

    finally:
        conn.close()

    # ✅ Trả về giao diện (tab Phòng ban mở mặc định)
    return render_template(
        "deleted_records.html",
        deleted_employees=deleted_employees,
        deleted_departments=deleted_departments,
        active_tab="departments"
    )


# QUẢN LÝ CA LÀM

from datetime import datetime, time

@app.route("/shifts")
@require_role("admin")
def shifts():
    from datetime import datetime
    keyword = request.args.get("q", "").strip().lower()

    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🟢 Chỉ lấy những ca đang hoạt động (TrangThai = 1)
    cursor.execute("""
        SELECT MaCa, TenCa, GioBatDau, GioKetThuc, HeSo, MoTa
        FROM CaLamViec
        WHERE TrangThai = 1
        ORDER BY MaCa
    """)
    rows = cursor.fetchall()

    shifts = []
    for row in rows:
        ma_ca, ten_ca, gio_bd, gio_kt, he_so, mo_ta = row

        def fmt(t):
            try:
                if isinstance(t, str):
                    return t[:5]
                return t.strftime("%H:%M")
            except Exception:
                return str(t)

        gio_bd_fmt = fmt(gio_bd)
        gio_kt_fmt = fmt(gio_kt)

        now_time = datetime.now().strftime("%H:%M")
        trang_thai = "Đang hoạt động" if gio_bd_fmt <= now_time <= gio_kt_fmt else "Ngoài giờ"

        shifts.append({
            "MaCa": ma_ca,
            "TenCa": ten_ca,
            "GioBatDau": gio_bd_fmt,
            "GioKetThuc": gio_kt_fmt,
            "HeSoLuong": he_so,
            "MoTa": mo_ta,
            "TrangThai": trang_thai,
            "ThoiGian": f"{gio_bd_fmt} - {gio_kt_fmt}",
            "LastUpdated": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        })

    if keyword:
        shifts = [
            s for s in shifts
            if keyword in s["TenCa"].lower() or keyword in s["MaCa"].lower()
        ]

    # 🧮 Tổng số ca làm việc (đang hoạt động)
    cursor.execute("SELECT COUNT(*) FROM CaLamViec WHERE TrangThai = 1")
    total_shifts = cursor.fetchone()[0]

    # 🧮 Tổng số ca đang hoạt động theo thời gian thực
    active_shifts = sum(1 for s in shifts if s["TrangThai"] == "Đang hoạt động")

    # 🧮 Tổng số nhân viên đã được phân ca
    cursor.execute("SELECT COUNT(DISTINCT MaNV) FROM LichLamViec")
    total_assigned = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "shifts.html",
        shifts=shifts,
        total_shifts=total_shifts,
        active_shifts=active_shifts,
        total_employees=total_assigned,
        keyword=keyword
    )

#chi tiết ca
@app.route("/shifts/<ma_ca>")
@require_role("admin")
def shift_detail(ma_ca):
    from datetime import datetime
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy thông tin ca làm ---
    cursor.execute("""
        SELECT 
            MaCa, 
            TenCa, 
            GioBatDau, 
            GioKetThuc, 
            HeSo, 
            MoTa, 
            FORMAT(NgayCapNhat, 'dd/MM/yyyy HH:mm:ss') AS NgayCapNhat
        FROM CaLamViec
        WHERE MaCa = ?
    """, (ma_ca,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("❌ Không tìm thấy ca làm việc!", "error")
        return redirect(url_for("shifts"))

    # --- Gán dữ liệu ---
    ma_ca, ten_ca, gio_bd, gio_kt, he_so, mo_ta, ngay_cap_nhat = row

    def fmt_time(t):
        try:
            if isinstance(t, str):
                return t[:5]
            return t.strftime("%H:%M")
        except Exception:
            return str(t)

    gio_bd_fmt = fmt_time(gio_bd)
    gio_kt_fmt = fmt_time(gio_kt)
    now_str = datetime.now().strftime("%H:%M")

    ca_info = {
        "ma_ca": ma_ca,
        "ten_ca": ten_ca,
        "gio_bd": gio_bd_fmt,
        "gio_kt": gio_kt_fmt,
        "he_so": he_so if he_so else "—",
        "mo_ta": mo_ta if mo_ta else "Không có mô tả",
        "trang_thai": "Đang hoạt động" if gio_bd_fmt <= now_str <= gio_kt_fmt else "Ngoài giờ",
        "last_updated": ngay_cap_nhat if ngay_cap_nhat else "Chưa cập nhật"
    }

    # --- Ghi lịch sử xem chi tiết ---
    try:
        username = session.get("username") or session.get("user_id") or "admin"
        cursor.execute("EXEC sys.sp_set_session_context @key=N'user', @value=?", (username,))
        cursor.execute("""
            INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, ThoiGian, NguoiThucHien)
            VALUES (N'CaLamViec', ?, N'Xem chi tiết', GETDATE(), ?)
        """, (ma_ca, username))
        conn.commit()
    except Exception as e:
        print("⚠️ Lỗi ghi log xem chi tiết ca làm việc:", e)

    # --- Lấy danh sách nhân viên thuộc ca ---
    keyword = request.args.get("q", "").strip()
    order = request.args.get("sort", "ten")

    query = """
        SELECT nv.MaNV, nv.HoTen, pb.TenPB, nv.ChucVu
        FROM LichLamViec llv
        JOIN NhanVien nv ON llv.MaNV = nv.MaNV
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        WHERE llv.MaCa = ?
    """
    params = [ma_ca]

    if keyword:
        query += " AND (nv.HoTen LIKE ? OR nv.MaNV LIKE ? OR pb.TenPB LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"])

    if order == "ten":
        query += " ORDER BY nv.HoTen"
    elif order == "phongban":
        query += " ORDER BY pb.TenPB"
    else:
        query += " ORDER BY nv.MaNV"

    cursor.execute(query, params)
    nhanviens = cursor.fetchall()
    conn.close()

    # --- Render ra template ---
    return render_template(
        "shift_detail.html",
        ca=ca_info,
        nhanviens=nhanviens,
        keyword=keyword,
        order=order
    )


@app.route("/add_shift", methods=["GET", "POST"])
@require_role("admin")
def add_shift():
    if request.method == "POST":
        ten_ca = request.form["ten_ca"]
        gio_bd = request.form["gio_bat_dau"]
        gio_kt = request.form["gio_ket_thuc"]
        he_so = request.form.get("he_so", 1.0)
        mo_ta = request.form.get("mo_ta", "")

        new_ma_ca = manage_shift.add_shift(ten_ca, gio_bd, gio_kt, he_so, mo_ta)
        flash(f"✅ Thêm ca làm mới thành công! Mã ca: {new_ma_ca}", "success")
        return redirect(url_for("shifts"))

    return render_template("add_shift.html")

#Chỉnh sửa ca
@app.route("/edit_shift/<ma_ca>", methods=["GET", "POST"])
@require_role("admin")
def edit_shift(ma_ca):
    conn = get_sql_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        ten_ca = request.form.get("ten_ca")
        gio_bat_dau = request.form.get("gio_bat_dau")
        gio_ket_thuc = request.form.get("gio_ket_thuc")
        he_so = request.form.get("he_so")

        try:
            # 🔹 Lấy dữ liệu cũ để ghi log thay đổi
            cursor.execute("""
                SELECT TenCa, GioBatDau, GioKetThuc, HeSo
                FROM CaLamViec
                WHERE MaCa = ?
            """, (ma_ca,))
            old_data = cursor.fetchone()
            old_values = {
                "TenCa": old_data[0],
                "GioBatDau": str(old_data[1]),
                "GioKetThuc": str(old_data[2]),
                "HeSo": str(old_data[3])
            } if old_data else {}

            # 🔹 Cập nhật dữ liệu mới
            cursor.execute("""
                UPDATE CaLamViec
                SET TenCa = ?, GioBatDau = ?, GioKetThuc = ?, HeSo = ?, NgayCapNhat = GETDATE()
                WHERE MaCa = ?
            """, (ten_ca, gio_bat_dau, gio_ket_thuc, he_so, ma_ca))

            # 🔹 So sánh và ghi vào bảng LichSuThayDoi
            new_values = {
                "TenCa": ten_ca,
                "GioBatDau": gio_bat_dau,
                "GioKetThuc": gio_ket_thuc,
                "HeSo": he_so
            }
            username = session.get("username", "Hệ thống")

            for field in new_values:
                old_val = old_values.get(field)
                new_val = new_values[field]
                if str(old_val) != str(new_val):  # chỉ ghi nếu có thay đổi
                    cursor.execute("""
                        INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
                        VALUES (?, ?, N'Sửa', ?, ?, ?, GETDATE(), ?)
                    """, ('CaLamViec', ma_ca, field, old_val, new_val, username))

            conn.commit()
            flash("✅ Cập nhật ca làm việc thành công!", "success")
            return redirect(url_for("shifts"))

        except Exception as e:
            conn.rollback()
            flash(f"❌ Lỗi khi cập nhật ca làm việc: {e}", "error")

    # --- Lấy dữ liệu ca để hiển thị form ---
    cursor.execute("""
        SELECT 
            CLV.MaCa,
            CLV.TenCa,
            CONVERT(CHAR(5), CLV.GioBatDau, 108) AS GioBatDau,
            CONVERT(CHAR(5), CLV.GioKetThuc, 108) AS GioKetThuc,
            CLV.HeSo,
            ISNULL(CLV.MoTa, '') AS MoTa
        FROM CaLamViec CLV
        WHERE CLV.MaCa = ?
    """, (ma_ca,))

    row = cursor.fetchone()
    if row:
        columns = [col[0] for col in cursor.description]
        ca = dict(zip(columns, row))
    else:
        conn.close()
        flash(f"❌ Không tìm thấy ca làm việc {ma_ca}", "error")
        return redirect(url_for("shifts"))

    conn.close()
    return render_template("edit_shift.html", ca=ca)

#Xóa ca
# --- Xóa mềm 1 hoặc nhiều ca ---
# 🔹 XÓA MỀM 1 HOẶC NHIỀU CA LÀM VIỆC
@app.route("/delete_shift", methods=["POST"])
@require_role("admin")
def delete_shift():
    from flask import request
    ma_ca_list = request.form.getlist("ma_ca")  # Lấy danh sách mã ca (có thể nhiều)
    
    if not ma_ca_list:
        flash("⚠️ Vui lòng chọn ít nhất một ca làm việc để xóa!", "warning")
        return redirect(url_for("shifts"))
    
    try:
        # Gọi hàm xóa mềm trong module manage_shift
        manage_shift.delete_shift(ma_ca_list)

        if len(ma_ca_list) == 1:
            flash(f"🗑️ Đã xóa mềm ca {ma_ca_list[0]}!", "danger")
        else:
            flash(f"🗑️ Đã xóa mềm {len(ma_ca_list)} ca làm việc!", "danger")

    except Exception as e:
        flash(f"❌ Lỗi khi xóa ca làm việc: {e}", "error")

    # Quay lại danh sách ca hoạt động
    return redirect(url_for("shifts"))

# --- Danh sách ca đã xóa ---
@app.route("/deleted_shifts")
@require_role("admin")
def deleted_shifts():
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MaCa, TenCa, GioBatDau, GioKetThuc, MoTa, HeSo, NgayCapNhat
        FROM CaLamViec
        WHERE TrangThai = 0
        ORDER BY NgayCapNhat DESC
    """)
    deleted_list = cursor.fetchall()
    conn.close()
    return render_template(
        "deleted_records.html",
        active_tab="shifts",
        deleted_shifts=deleted_list
    )

# ============================================================
# 🔄 KHÔI PHỤC 1 HOẶC NHIỀU CA LÀM VIỆC
# ============================================================
@app.route("/restore_shift", methods=["POST"])
@require_role("admin")
def restore_shift():
    ma_ca_list = request.form.getlist("selected_ids")

    if not ma_ca_list:
        flash("⚠️ Chưa chọn ca nào để khôi phục!", "warning")
        return redirect(url_for("deleted_shifts"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for ma_ca in ma_ca_list:
            # 🔹 Cập nhật lại trạng thái hoạt động
            cursor.execute("""
                UPDATE CaLamViec
                SET TrangThai = 1
                WHERE MaCa = ?
            """, (ma_ca,))

            # 🔹 Ghi log khôi phục
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "CaLamViec",
                ma_ca,
                "Khôi phục",
                "TrangThai",
                0, 1,
                username
            ))

        conn.commit()
        flash(f"✅ Đã khôi phục {len(ma_ca_list)} ca làm việc!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục ca làm việc: {e}", "danger")

    finally:
        conn.close()

    return redirect(url_for("deleted_shifts"))

#  Trang danh sách nhân viên đã phân ca

@app.route("/assigned_employees")
@require_role("admin")
def assigned_employees():
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    today = now.date()

    # ==========================================================
    # 🔹 1. Cập nhật trạng thái "Vắng" tự động
    # ==========================================================
    cursor.execute("""
        UPDATE llv
        SET llv.TrangThai = 2
        FROM LichLamViec llv
        LEFT JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
        WHERE llv.TrangThai = 0
          AND llv.DaXoa = 1   -- ✅ chỉ cập nhật với các phân ca đang hoạt động
          AND (
                llv.NgayLam < CAST(GETDATE() AS DATE)
                OR (llv.NgayLam = CAST(GETDATE() AS DATE)
                    AND CONVERT(TIME, GETDATE()) > clv.GioKetThuc)
              )
          AND NOT EXISTS (
                SELECT 1 FROM ChamCong cc
                WHERE cc.MaNV = llv.MaNV 
                  AND cc.NgayChamCong = llv.NgayLam
                  AND cc.MaCa = llv.MaCa
              )
    """)
    conn.commit()

    # ==========================================================
    # 🔹 2. Lấy danh sách phân ca đang hoạt động (DaXoa = 1)
    # ==========================================================
    cursor.execute("""
        SELECT 
            llv.MaLLV,
            nv.MaNV,
            nv.HoTen,
            pb.TenPB,
            clv.TenCa,
            clv.GioBatDau,
            clv.GioKetThuc,

            -- ✅ Giờ chấm công thực tế
            FORMAT(cc.GioVao, 'HH:mm') AS GioVao,
            FORMAT(cc.GioRa, 'HH:mm') AS GioRa,

            llv.NgayLam,

            -- ✅ Nếu có chấm công thì xem là đã chấm
            CASE 
                WHEN cc.MaChamCong IS NOT NULL THEN 1
                ELSE llv.TrangThai
            END AS TrangThai,

            CASE 
                WHEN cc.MaChamCong IS NOT NULL THEN N'Đã chấm công'
                WHEN llv.TrangThai = 0 THEN N'Chưa chấm'
                WHEN llv.TrangThai = 2 THEN N'Vắng'
                ELSE N'Không xác định'
            END AS TrangThaiText

        FROM LichLamViec llv
        LEFT JOIN NhanVien nv ON llv.MaNV = nv.MaNV
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN CaLamViec clv ON llv.MaCa = clv.MaCa

        -- ✅ JOIN phụ lọc 1 bản ghi ChamCong duy nhất / nhân viên / ngày / ca
        OUTER APPLY (
            SELECT TOP 1 c.GioVao, c.GioRa, c.MaChamCong
            FROM ChamCong c
            WHERE c.MaNV = llv.MaNV 
            AND c.NgayChamCong = llv.NgayLam
            AND (c.MaCa = llv.MaCa OR c.MaCa IS NULL)
            ORDER BY 
                CASE WHEN c.MaCa = llv.MaCa THEN 0 ELSE 1 END, 
                c.GioVao ASC
        ) AS cc

        WHERE llv.DaXoa = 1    -- ✅ chỉ lấy phân ca chưa bị xóa mềm

        ORDER BY llv.NgayLam DESC, nv.HoTen, clv.TenCa
    """)

    # ==========================================================
    # 🔹 3. Chuyển đổi dữ liệu sang dict + định dạng
    # ==========================================================
    columns = [col[0] for col in cursor.description]
    records = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()

    # ==========================================================
    # 🔹 4. Hàm xử lý dữ liệu ngày và giờ
    # ==========================================================
    def to_date(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d").date()
            except:
                return None
        return None

    def to_time(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.time()
        if isinstance(value, str):
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(value.strip(), fmt).time()
                except:
                    pass
            return None
        return None

    def fmt_time(t):
        return t.strftime("%H:%M") if t else "-"

    # ==========================================================
    # 🔹 5. Làm sạch dữ liệu & format giờ để render
    # ==========================================================
    for r in records:
        r["NgayLam"] = to_date(r.get("NgayLam"))
        r["GioBatDau"] = to_time(r.get("GioBatDau"))
        r["GioKetThuc"] = to_time(r.get("GioKetThuc"))
        r["GioVao"] = to_time(r.get("GioVao"))
        r["GioRa"] = to_time(r.get("GioRa"))

        r["GioBatDauText"] = fmt_time(r["GioBatDau"])
        r["GioKetThucText"] = fmt_time(r["GioKetThuc"])
        r["GioVaoText"] = fmt_time(r["GioVao"])
        r["GioRaText"] = fmt_time(r["GioRa"])

    # ==========================================================
    # 🔹 6. Thống kê tổng hợp
    # ==========================================================
    present_count = sum(1 for r in records if r["TrangThai"] == 1)
    absent_count = sum(1 for r in records if r["TrangThai"] == 2)
    pending_count = sum(1 for r in records if r["TrangThai"] == 0)
    total_count = len(records)

    # ==========================================================
    # 🔹 7. Trả về template
    # ==========================================================
    return render_template(
        "assigned_employees.html",
        records=records,
        present_count=present_count,
        absent_count=absent_count,
        pending_count=pending_count,
        total_count=total_count
    )


@app.route("/api/schedule/<ma_nv>")
def api_schedule(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT CONVERT(varchar, NgayLam, 23), CLV.TenCa
        FROM LichLamViec LLV
        JOIN CaLamViec CLV ON LLV.MaCa = CLV.MaCa
        WHERE LLV.MaNV = ?
    """, (ma_nv,))
    data = [{"date": r[0], "shift": r[1]} for r in cursor.fetchall()]
    conn.close()
    return jsonify(data)

# Trang phân ca mới
# ======================
@app.route("/assign_shift", methods=["GET", "POST"])
@require_role("admin")
def assign_shift():
    conn = get_sql_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        # 🔹 Lấy dữ liệu từ form
        MaNV_list = request.form.getlist("MaNV[]")      # Nhiều nhân viên
        MaCa_list = request.form.getlist("MaCa[]")      # Nhiều ca
        NgayLam_raw = request.form.get("NgayLam[]") or request.form.getlist("NgayLam[]")

        # ✅ Chuẩn hóa danh sách ngày (Flatpickr gửi chuỗi phân tách bằng dấu phẩy)
        if isinstance(NgayLam_raw, str):
            NgayLam_list = [d.strip() for d in NgayLam_raw.split(",") if d.strip()]
        else:
            NgayLam_list = NgayLam_raw

        # Kiểm tra dữ liệu
        if not MaNV_list or not MaCa_list or not NgayLam_list:
            flash("⚠️ Vui lòng chọn ít nhất 1 nhân viên, 1 ca và 1 ngày!", "danger")
            return redirect(url_for("assign_shift"))

        inserted, skipped = 0, 0

        # 🔹 Lặp qua từng nhân viên, từng ngày, từng ca
        for ma_nv in MaNV_list:
            for ma_ca in MaCa_list:
                for ngay in NgayLam_list:
                    cursor.execute("""
                        SELECT COUNT(*) 
                        FROM LichLamViec
                        WHERE MaNV = ? AND MaCa = ? AND NgayLam = ?
                    """, (ma_nv, ma_ca, ngay))
                    exists = cursor.fetchone()[0]

                    if not exists:
                        cursor.execute("""
                            INSERT INTO LichLamViec (MaNV, MaCa, NgayLam, TrangThai, DaXoa)
                            VALUES (?, ?, ?, 0, 1)
                        """, (ma_nv, ma_ca, ngay))
                        inserted += 1
                    else:
                        skipped += 1

        conn.commit()
        conn.close()

        flash(f"✅ Đã phân {inserted} ca, bỏ qua {skipped} ca trùng!", "success")
        return redirect(url_for("assigned_employees"))

    # --- Khi GET form ---
    cursor.execute("""
        SELECT MaNV, HoTen 
        FROM NhanVien 
        WHERE TrangThai = 1
        ORDER BY HoTen
    """)
    employees = cursor.fetchall()

    cursor.execute("""
        SELECT MaCa, TenCa 
        FROM CaLamViec 
        WHERE TrangThai = 1
        ORDER BY MaCa
    """)
    shifts = cursor.fetchall()

    conn.close()

    return render_template("assign_shift.html", employees=employees, shifts=shifts)


# Sửa phân ca
@app.route("/edit_shift_assignment/<int:id>", methods=["GET", "POST"])
@require_role("admin")
def edit_shift_assignment(id):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # Lấy dữ liệu hiện tại
    cursor.execute("""
        SELECT LLV.MaLLV, LLV.MaNV, LLV.MaCa, LLV.NgayLam, NV.HoTen, CLV.TenCa
        FROM LichLamViec LLV
        LEFT JOIN NhanVien NV ON NV.MaNV = LLV.MaNV
        LEFT JOIN CaLamViec CLV ON CLV.MaCa = LLV.MaCa
        WHERE LLV.MaLLV = ?
    """, (id,))
    record = cursor.fetchone()

    # Nếu có giá trị ngày, ép kiểu thành datetime để HTML dùng .strftime()
    if record and isinstance(record.NgayLam, str):
        try:
            record.NgayLam = datetime.strptime(record.NgayLam, "%Y-%m-%d")
        except ValueError:
            record.NgayLam = None

    # Lấy danh sách nhân viên & ca làm
    cursor.execute("SELECT MaNV, HoTen FROM NhanVien")
    employees = cursor.fetchall()

    cursor.execute("SELECT MaCa, TenCa FROM CaLamViec")
    shifts = cursor.fetchall()

    # Khi người dùng bấm “Lưu”
    if request.method == "POST":
        MaNV = request.form.get("MaNV")
        MaCa = request.form.get("MaCa")
        NgayLam = request.form.get("NgayLam")

        cursor.execute("""
            UPDATE LichLamViec
            SET MaNV=?, MaCa=?, NgayLam=?
            WHERE MaLLV=?
        """, (MaNV, MaCa, NgayLam, id))
        conn.commit()
        conn.close()
        flash("Đã cập nhật thông tin phân ca!", "success")
        return redirect(url_for("assigned_employees"))

    conn.close()
    return render_template("edit_shift_assignment.html", record=record, employees=employees, shifts=shifts)

# ===========================
# 🔹 Xóa mềm 1 phân ca
# ===========================
@app.route("/delete_shift_assignment/<id>")
@require_role("admin")
def delete_shift_assignment(id):
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Lấy thông tin trước khi xóa
        cursor.execute("""
            SELECT DaXoa, MaNV, MaCa, NgayLam
            FROM LichLamViec
            WHERE MaLLV = ?
        """, (id,))
        old_data = cursor.fetchone()

        if not old_data:
            flash("❌ Không tìm thấy phân ca để xóa!", "error")
            return redirect(url_for("assigned_employees"))

        # ✅ Cập nhật DaXoa = 0 (xóa mềm)
        cursor.execute("""
            UPDATE LichLamViec
            SET DaXoa = 0
            WHERE MaLLV = ?
        """, (id,))

        # ✅ Ghi log thay đổi
        username = session.get("username", "Hệ thống")
        cursor.execute("""
            INSERT INTO LichSuThayDoi 
            (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "LichLamViec", id, "Xóa mềm",
            "DaXoa", str(old_data[0]), "0",
            datetime.now(), username
        ))

        conn.commit()
        flash("🗑️ Đã xóa mềm phân ca và ghi vào lịch sử!", "warning")

    except Exception as e:
        conn.rollback()
        flash(f"⚠️ Lỗi khi xóa phân ca: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("assigned_employees"))


# ===========================
# 🔹 Xóa mềm nhiều phân ca
# ===========================
@app.route("/delete_shift_assignment", methods=["POST"])
@require_role("admin")
def delete_multiple_shift_assignments():
    selected_ids = request.form.getlist("selected_assignments")
    if not selected_ids:
        flash("⚠️ Chưa chọn phân ca nào để xóa!", "warning")
        return redirect(url_for("assigned_employees"))

    conn = get_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for record_id in selected_ids:
            cursor.execute("SELECT DaXoa FROM LichLamViec WHERE MaLLV = ?", (record_id,))
            old_data = cursor.fetchone()

            if old_data:
                # ✅ Xóa mềm
                cursor.execute("UPDATE LichLamViec SET DaXoa = 0 WHERE MaLLV = ?", (record_id,))

                # ✅ Ghi log thay đổi
                cursor.execute("""
                    INSERT INTO LichSuThayDoi 
                    (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    "LichLamViec", record_id, "Xóa mềm",
                    "DaXoa", str(old_data[0]), "0",
                    datetime.now(), username
                ))

        conn.commit()
        flash(f"🗑️ Đã xóa mềm {len(selected_ids)} phân ca và ghi vào lịch sử!", "warning")

    except Exception as e:
        conn.rollback()
        flash(f"⚠️ Lỗi khi xóa nhiều phân ca: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("assigned_employees"))


# ===========================
# 🔹 Khôi phục phân ca
# ===========================
@app.route("/restore_shift_assignment/<id>", methods=["POST"])
@require_role("admin")
def restore_shift_assignment(id):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # Lấy thông tin trước khi khôi phục
        cursor.execute("""
            SELECT DaXoa, MaNV, MaCa, NgayLam
            FROM LichLamViec
            WHERE MaLLV = ?
        """, (id,))
        old_data = cursor.fetchone()

        if not old_data:
            flash("❌ Không tìm thấy phân ca cần khôi phục!", "error")
            return redirect(url_for("deleted_shift_assignments_list"))

        # ✅ Cập nhật DaXoa = 1 (khôi phục)
        cursor.execute("""
            UPDATE LichLamViec
            SET DaXoa = 1
            WHERE MaLLV = ?
        """, (id,))

        # ✅ Ghi log khôi phục
        username = session.get("username", "Hệ thống")
        cursor.execute("""
            INSERT INTO LichSuThayDoi 
            (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "LichLamViec", id, "Khôi phục",
            "DaXoa", str(old_data[0]), "1",
            datetime.now(), username
        ))

        conn.commit()
        flash("✅ Đã khôi phục phân ca và ghi vào lịch sử!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"⚠️ Lỗi khi khôi phục phân ca: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("deleted_shift_assignments_list"))

# ============================================================
# 🔄 KHÔI PHỤC NHIỀU PHÂN CA ĐÃ XÓA
# ============================================================
@app.route("/restore_shift_assignments", methods=["POST"])
@require_role("admin")
def restore_multiple_shift_assignments():
    selected_ids = request.form.getlist("selected_assignments")

    if not selected_ids:
        flash("⚠️ Chưa chọn phân ca nào để khôi phục!", "warning")
        return redirect(url_for("deleted_shift_assignments_list"))  # hoặc deleted_shift_assignments nếu endpoint khác

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for record_id in selected_ids:
            cursor.execute("""
                SELECT DaXoa FROM LichLamViec WHERE MaLLV = ?
            """, (record_id,))
            old_data = cursor.fetchone()

            if not old_data:
                continue

            # ✅ Cập nhật lại trạng thái (DaXoa = 1)
            cursor.execute("""
                UPDATE LichLamViec
                SET DaXoa = 1
                WHERE MaLLV = ?
            """, (record_id,))

            # ✅ Ghi log khôi phục
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "LichLamViec",
                record_id,
                "Khôi phục nhiều",
                "DaXoa",
                0, 1,
                username
            ))

        conn.commit()
        flash(f"✅ Đã khôi phục {len(selected_ids)} phân ca!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục nhiều phân ca: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("deleted_shift_assignments_list"))  # đổi theo endpoint thực tế của bạn

# ===========================
# 🔹 Hiển thị danh sách phân ca đã xóa mềm
# ===========================
@app.route("/deleted_records/shift_assignments")
@require_role("admin")
def deleted_shift_assignments_list():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # ==========================================================
        # 🔹 Lấy danh sách phân ca đã xóa (DaXoa = 0)
        # ==========================================================
        cursor.execute("""
            SELECT 
                llv.MaLLV,
                llv.MaNV,
                nv.HoTen,
                pb.TenPB,
                clv.TenCa,
                llv.NgayLam,
                clv.GioBatDau,
                clv.GioKetThuc,

                -- ✅ Giờ chấm công thực tế (nếu có)
                FORMAT(cc.GioVao, 'HH:mm') AS GioVao,
                FORMAT(cc.GioRa, 'HH:mm') AS GioRa,

                -- ✅ Xác định trạng thái chính xác
                CASE 
                    WHEN cc.MaChamCong IS NOT NULL THEN 1   -- Đã chấm công
                    WHEN llv.TrangThai = 2 THEN 2           -- Vắng
                    ELSE 0                                 -- Chưa chấm công
                END AS TrangThai,

                CASE 
                    WHEN cc.MaChamCong IS NOT NULL THEN N'Đã chấm công'
                    WHEN llv.TrangThai = 2 THEN N'Vắng'
                    WHEN llv.TrangThai = 0 THEN N'Chưa chấm công'
                    ELSE N'Không xác định'
                END AS TrangThaiText

            FROM LichLamViec llv
            LEFT JOIN NhanVien nv ON llv.MaNV = nv.MaNV
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            LEFT JOIN CaLamViec clv ON llv.MaCa = clv.MaCa

            OUTER APPLY (
                SELECT TOP 1 c.GioVao, c.GioRa, c.MaChamCong
                FROM ChamCong c
                WHERE c.MaNV = llv.MaNV 
                  AND c.NgayChamCong = llv.NgayLam
                  AND (c.MaCa = llv.MaCa OR c.MaCa IS NULL)
                ORDER BY 
                    CASE WHEN c.MaCa = llv.MaCa THEN 0 ELSE 1 END,
                    c.GioVao ASC
            ) AS cc

            WHERE llv.DaXoa = 0
            ORDER BY llv.NgayLam DESC, nv.HoTen
        """)

        deleted_shift_assignments = cursor.fetchall()

    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách phân ca đã xóa: {e}", "danger")
        deleted_shift_assignments = []

    finally:
        conn.close()

    # ==========================================================
    # 🔹 Render ra template giao diện deleted_records.html
    # ==========================================================
    return render_template(
        "deleted_records.html",
        active_tab="shift_assignments",
        deleted_shift_assignments=deleted_shift_assignments
    )



# QUẢN LÝ TÀI KHOẢN

# ========== DANH SÁCH TÀI KHOẢN ==========
@app.route("/accounts")
@require_role("admin")
def accounts():
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Thống kê tổng quan ---
    cursor.execute("SELECT COUNT(*) FROM TaiKhoan WHERE TrangThai = 1")
    total_accounts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM TaiKhoan WHERE TrangThai = 1")
    active_accounts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM TaiKhoan WHERE TrangThai = 0")
    inactive_accounts = cursor.fetchone()[0]

    # 🧮 Tổng số tài khoản quản trị (đang hoạt động)
    cursor.execute("""
        SELECT COUNT(*) 
        FROM TaiKhoan
        WHERE TrangThai = 1
        AND LOWER(VaiTro) IN (N'admin', N'quản trị viên', N'administrator')
    """)
    admin_accounts = cursor.fetchone()[0]

    # 🧮 Tổng số tài khoản người dùng (đang hoạt động)
    cursor.execute("""
        SELECT COUNT(*) 
        FROM TaiKhoan
        WHERE TrangThai = 1
        AND LOWER(VaiTro) IN (N'user', N'nhanvien', N'nhân viên', N'người dùng')
    """)
    user_accounts = cursor.fetchone()[0]


    # --- Lấy danh sách tài khoản đang hoạt động ---
    cursor.execute("""
        SELECT 
            t.MaTK,
            t.TenDangNhap,
            ISNULL(n.HoTen, N'—') AS HoTen,
            ISNULL(n.Email, N'—') AS Email,
            CASE 
                WHEN LOWER(t.VaiTro) IN (N'admin', N'quản trị viên', N'administrator') THEN N'Quản trị viên'
                WHEN LOWER(t.VaiTro) IN (N'user', N'nhanvien', N'nhân viên', N'người dùng') THEN N'Nhân viên'
                ELSE ISNULL(t.VaiTro, N'Không xác định')
            END AS VaiTro,
            CASE 
                WHEN t.TrangThai = 1 THEN N'Đang hoạt động'
                ELSE N'Ngừng hoạt động'
            END AS TrangThai,
            t.TrangThai AS TrangThaiCode,
            CONVERT(VARCHAR(10), t.NgayTao, 103) AS NgayTao
        FROM TaiKhoan t
        LEFT JOIN NhanVien n ON t.MaNV = n.MaNV
        WHERE t.TrangThai = 1                -- 🟢 chỉ lấy tài khoản hoạt động
        ORDER BY t.NgayTao DESC
    """)
    accounts = cursor.fetchall()

    conn.close()

    # --- Trả dữ liệu ra giao diện ---
    return render_template(
        "accounts.html",
        accounts=accounts,
        total_accounts=total_accounts,
        active_accounts=active_accounts,
        inactive_accounts=inactive_accounts,
        admin_accounts=admin_accounts,
        user_accounts=user_accounts
    )

# ========== THÊM TÀI KHOẢN ==========
@app.route("/add_account", methods=["GET", "POST"])
@require_role("admin")
def add_account_route():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()

        if not username or not password or not role:
            flash("⚠️ Vui lòng nhập đầy đủ thông tin!", "danger")
            return redirect(url_for("add_account_route"))

        hashed_password = hashlib.sha256(password.encode("utf-8")).hexdigest()

        conn = get_sql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO TaiKhoan (TenDangNhap, MatKhauHash, VaiTro, TrangThai, NgayTao)
            VALUES (?, ?, ?, 1, GETDATE())
        """, (username, hashed_password, role))

        # Ghi log (nếu có bảng LichSuThayDoi)
        cursor.execute("""
            INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES ('TaiKhoan', ?, N'Thêm', N'Toàn bộ', NULL, ?, GETDATE(), ?)
        """, (username, username, session.get("user_id")))

        conn.commit()
        conn.close()

        flash("✅ Thêm tài khoản thành công!", "success")
        return redirect(url_for("accounts"))

    return render_template("add_account.html")


# ========== SỬA TÀI KHOẢN ==========
@app.route("/edit_account/<username>", methods=["GET", "POST"])
@require_role("admin")
def edit_account(username):
    conn = get_sql_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()

        if password:
            hashed_password = hashlib.sha256(password.encode("utf-8")).hexdigest()
            cursor.execute("""
                UPDATE TaiKhoan
                SET MatKhauHash = ?, VaiTro = ?
                WHERE TenDangNhap = ?
            """, (hashed_password, role, username))
        else:
            cursor.execute("""
                UPDATE TaiKhoan
                SET VaiTro = ?
                WHERE TenDangNhap = ?
            """, (role, username))

        # Ghi log thay đổi
        cursor.execute("""
            INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES ('TaiKhoan', ?, N'Cập nhật', N'VaiTro / MatKhau', NULL, ?, GETDATE(), ?)
        """, (username, role, session.get("user_id")))

        conn.commit()
        conn.close()
        flash("📝 Cập nhật tài khoản thành công!", "success")
        return redirect(url_for("accounts"))

    # Lấy thông tin hiện tại
    cursor.execute("SELECT TenDangNhap, VaiTro FROM TaiKhoan WHERE TenDangNhap = ?", (username,))
    account = cursor.fetchone()
    conn.close()

    if not account:
        flash("❌ Không tìm thấy tài khoản.", "danger")
        return redirect(url_for("accounts"))

    return render_template("edit_account.html", account=account)


# ========== VÔ HIỆU HÓA (XÓA MỀM) ==========
@app.route("/accounts/deactivate/<username>", methods=["POST"])
@require_role("admin")
def deactivate_account(username):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE TaiKhoan SET TrangThai = 0 WHERE TenDangNhap = ?", (username,))

    cursor.execute("""
        INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
        VALUES ('TaiKhoan', ?, N'Vô hiệu hóa', N'TrangThai', 1, 0, GETDATE(), ?)
    """, (username, session.get("user_id")))

    conn.commit()
    conn.close()
    flash(f"🗑️ Đã vô hiệu hóa tài khoản: {username}", "warning")
    return redirect(url_for("accounts"))


# ========== KÍCH HOẠT (KHÔI PHỤC) ==========
@app.route("/accounts/activate/<username>", methods=["POST"])
@require_role("admin")
def activate_account(username):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE TaiKhoan SET TrangThai = 1 WHERE TenDangNhap = ?", (username,))

    cursor.execute("""
        INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
        VALUES ('TaiKhoan', ?, N'Khôi phục', N'TrangThai', 0, 1, GETDATE(), ?)
    """, (username, session.get("user_id")))

    conn.commit()
    conn.close()
    flash(f"♻️ Đã kích hoạt tài khoản: {username}", "success")
    return redirect(url_for("accounts"))


# ========== CHUYỂN TRẠNG THÁI (AJAX) ==========
@app.route("/accounts/toggle_status/<username>", methods=["POST"])
@require_role("admin")
def toggle_account_status(username):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TrangThai FROM TaiKhoan WHERE TenDangNhap = ?", (username,))
    result = cursor.fetchone()

    if not result:
        conn.close()
        return jsonify({"success": False, "message": "Không tìm thấy tài khoản."})

    current_status = result[0]
    new_status = 0 if current_status == 1 else 1

    cursor.execute("UPDATE TaiKhoan SET TrangThai = ? WHERE TenDangNhap = ?", (new_status, username))
    cursor.execute("""
        INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
        VALUES ('TaiKhoan', ?, N'Thay đổi trạng thái', N'TrangThai', ?, ?, GETDATE(), ?)
    """, (username, current_status, new_status, session.get("user_id")))

    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "username": username,
        "new_status": new_status,
        "status_text": "Đang hoạt động" if new_status == 1 else "Ngừng hoạt động"
    })


# ========== XÓA MỀM TRỰC TIẾP ==========
@app.route("/delete_account/<username>", methods=["POST"])
@require_role("admin")
def delete_account(username):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE TaiKhoan SET TrangThai = 0 WHERE TenDangNhap = ?", (username,))
    cursor.execute("""
        INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
        VALUES ('TaiKhoan', ?, N'Xóa mềm', N'TrangThai', 1, 0, GETDATE(), ?)
    """, (username, session.get("user_id")))

    conn.commit()
    conn.close()
    flash(f"🗑️ Đã vô hiệu hóa tài khoản {username}.", "warning")
    return redirect(url_for("accounts"))


# ========== KHÔI PHỤC ==========
@app.route("/restore_account/<username>", methods=["POST"])
@require_role("admin")
def restore_account(username):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE TaiKhoan SET TrangThai = 1 WHERE TenDangNhap = ?", (username,))
    cursor.execute("""
        INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
        VALUES ('TaiKhoan', ?, N'Khôi phục', N'TrangThai', 0, 1, GETDATE(), ?)
    """, (username, session.get("user_id")))

    conn.commit()
    conn.close()
    flash(f"♻️ Đã khôi phục tài khoản {username}.", "success")
    return redirect(url_for("accounts"))

# ========== KHÔI PHỤC NHIỀU TÀI KHOẢN ==========
@app.route("/accounts/restore-multiple", methods=["POST"])
@require_role("admin")
def restore_multiple_accounts():
    selected_usernames = request.form.getlist("selected_accounts")

    if not selected_usernames:
        flash("⚠️ Chưa chọn tài khoản nào để khôi phục!", "warning")
        return redirect(url_for("deleted_accounts"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for uname in selected_usernames:
            # ✅ Cập nhật trạng thái
            cursor.execute("""
                UPDATE TaiKhoan
                SET TrangThai = 1
                WHERE TenDangNhap = ?
            """, (uname,))

            # ✅ Ghi log
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "TaiKhoan",
                uname,
                "Khôi phục nhiều",
                "TrangThai",
                0, 1,
                username
            ))

        conn.commit()
        flash(f"♻️ Đã khôi phục {len(selected_usernames)} tài khoản thành công.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục nhiều tài khoản: {e}", "danger")

    finally:
        conn.close()

    return redirect(url_for("deleted_accounts"))

# BÁO CÁO THỐNG KÊ

@app.route('/reports')
@require_role("admin")
def reports_view():
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- 1. Danh sách nhân viên ---
    cursor.execute("""
        SELECT NV.*, PB.TenPB,
               CASE NV.TrangThai 
                   WHEN 1 THEN N'Đang hoạt động'
                   ELSE N'Ngừng hoạt động'
               END AS TrangThaiText
        FROM NhanVien NV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
    """)
    columns = [col[0] for col in cursor.description]
    employees = [dict(zip(columns, row)) for row in cursor.fetchall()]

    # --- 2. Danh sách phòng ban ---
    cursor.execute("""
        SELECT PB.MaPB, PB.TenPB,
               COUNT(NV.MaNV) AS SoNhanVien,
               CASE 
                   WHEN LTRIM(RTRIM(LOWER(PB.TrangThai))) IN 
                        (N'đang hoạt động', N'active', N'1') 
                        THEN N'Đang hoạt động'
                   ELSE N'Ngừng hoạt động'
               END AS TrangThaiText
        FROM PhongBan PB
        LEFT JOIN NhanVien NV ON PB.MaPB = NV.MaPB
        GROUP BY PB.MaPB, PB.TenPB, PB.TrangThai
        ORDER BY PB.MaPB
    """)
    columns_pb = [col[0] for col in cursor.description]
    departments = [dict(zip(columns_pb, row)) for row in cursor.fetchall()]

    # --- 3. Thống kê tổng quan ---
    total_employees = len(employees)

    # Đếm tất cả phòng ban, không phân biệt trạng thái
    total_departments = len(departments)

    # Nếu muốn chỉ đếm phòng ban "Đang hoạt động", dùng dòng này:
    # total_departments = sum(1 for dept in departments if dept['TrangThaiText'] == 'Đang hoạt động')

    attendance_rate = 96.5  # (có thể thay bằng tính toán thực tế)

    # Giờ trung bình mỗi tuần
    cursor.execute("SELECT AVG(DATEDIFF(hour, GioVao, GioRa)) FROM ChamCong")
    avg_hours_per_week = cursor.fetchone()[0] or 0

    # Tổng lương đã duyệt
    cursor.execute("SELECT SUM(TongTien) FROM Luong WHERE TrangThai = 1")
    total_salary = cursor.fetchone()[0] or 0

    # --- 4. Biểu đồ Chart.js ---

    # Pie chart: Tỉ lệ trạng thái nhân viên
    status_counts = {'Đang hoạt động': 0, 'Ngừng hoạt động': 0}
    for emp in employees:
        status_counts[emp['TrangThaiText']] += 1

    # Bar chart: Nhân viên theo phòng ban
    dept_counts = {}
    for emp in employees:
        dept_name = emp['TenPB'] or 'Chưa phân công'
        dept_counts[dept_name] = dept_counts.get(dept_name, 0) + 1

    # Pie chart: Giới tính
    gender_counts = {'Nam': 0, 'Nữ': 0}
    for emp in employees:
        if emp.get('GioiTinh') == 1:
            gender_counts['Nam'] += 1
        else:
            gender_counts['Nữ'] += 1

    # Bar chart: Nhân viên theo ca làm việc
    cursor.execute("""
        SELECT CL.TenCa, COUNT(LLV.MaNV)
        FROM LichLamViec LLV
        JOIN CaLamViec CL ON LLV.MaCa = CL.MaCa
        GROUP BY CL.TenCa
    """)
    shift_counts = dict(cursor.fetchall())
    total_shifts = len(shift_counts)
    max_shift_name = max(shift_counts, key=shift_counts.get) if shift_counts else None
    max_shift_count = shift_counts.get(max_shift_name, 0) if max_shift_name else 0

    conn.close()

    # --- 5. Trả dữ liệu ra template ---
    return render_template(
        'reports.html',
        employees=employees,
        departments=departments,
        total_employees=total_employees,
        total_departments=total_departments,
        attendance_rate=attendance_rate,
        avg_hours_per_week=avg_hours_per_week,
        total_salary=total_salary,
        status_counts=status_counts,
        dept_counts=dept_counts,
        gender_counts=gender_counts,
        shift_counts=shift_counts,
        total_shifts=total_shifts,
        max_shift_name=max_shift_name,
        max_shift_count=max_shift_count
    )

# BÁO CÁO CHẤM CÔNG

@app.route("/attendance_report", methods=["GET"])
@require_role("admin")
def attendance_report():
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lọc theo tháng / năm ---
    month = request.args.get("month")
    year = request.args.get("year")

    # ✅ Thêm điều kiện chỉ lấy bản ghi chưa xóa mềm
    filter_query, params = "WHERE CC.DaXoa = 1", []
    if month and year:
        filter_query += " AND MONTH(CC.NgayChamCong)=? AND YEAR(CC.NgayChamCong)=?"
        params = [month, year]
    elif year:
        filter_query += " AND YEAR(CC.NgayChamCong)=?"
        params = [year]

    # --- Lấy dữ liệu chấm công ---
    cursor.execute(f"""
        SELECT 
            CC.MaChamCong,
            NV.MaNV,
            NV.HoTen,
            PB.TenPB AS PhongBan,
            FORMAT(CC.NgayChamCong, 'yyyy-MM-dd') AS NgayChamCong,
            FORMAT(CC.GioVao, 'HH:mm') AS GioVao,
            FORMAT(CC.GioRa, 'HH:mm') AS GioRa,
            CLV.TenCa AS CaLam,
            COALESCE(CC.GioBatDauThucTe, CLV.GioBatDau) AS GioBatDauDung,
            COALESCE(CC.GioKetThucThucTe, CLV.GioKetThuc) AS GioKetThucDung,
            CASE 
                WHEN CC.GioRa IS NOT NULL 
                    THEN ROUND(DATEDIFF(MINUTE, CC.GioVao, CC.GioRa) / 60.0, 2)
                ELSE 0
            END AS SoGioLam,
            CASE 
                WHEN CC.GioVao IS NULL THEN N'Vắng'
                WHEN COALESCE(CC.GioBatDauThucTe, CLV.GioBatDau) IS NULL THEN N'Không xác định'
                ELSE 
                    CASE 
                        WHEN CAST(CC.GioVao AS TIME) > CAST(COALESCE(CC.GioBatDauThucTe, CLV.GioBatDau) AS TIME) 
                            THEN N'Đi muộn'
                        ELSE N'Đúng giờ'
                    END
            END AS TrangThaiText
        FROM ChamCong CC
        LEFT JOIN NhanVien NV ON CC.MaNV = NV.MaNV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        LEFT JOIN CaLamViec CLV ON CC.MaCa = CLV.MaCa
        {filter_query}
        ORDER BY CC.NgayChamCong DESC, NV.MaNV
    """, params)

    # --- Xử lý kết quả ---
    columns = [c[0] for c in cursor.description]
    records = [dict(zip(columns, row)) for row in cursor.fetchall()]

    # --- Thống kê ---
    total_records = len(records)
    total_on_time = sum(1 for r in records if r["TrangThaiText"] == "Đúng giờ")
    total_late = sum(1 for r in records if r["TrangThaiText"] == "Đi muộn")
    total_absent = sum(1 for r in records if r["TrangThaiText"] == "Vắng")
    attendance_rate = (total_on_time / total_records * 100) if total_records else 0

    conn.close()

    return render_template(
        "attendance_report.html",
        records=records,
        total_records=total_records,
        total_on_time=total_on_time,
        total_late=total_late,
        total_absent=total_absent,
        attendance_rate=attendance_rate,
        month=month,
        year=year
    )



#THÊM CHẤM CÔNG

@app.route("/attendance/add", methods=["GET", "POST"])
def add_attendance():
    conn = get_sql_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        try:
            MaNV = request.form["MaNV"]
            NgayChamCong = request.form["Ngay"]
            GioVao = request.form["GioVao"]
            GioRa = request.form.get("GioRa")
            TrangThai = int(request.form["TrangThai"])

            cursor.execute("""
                INSERT INTO ChamCong (MaNV, NgayChamCong, GioVao, GioRa, TrangThai)
                VALUES (?, ?, ?, ?, ?)
            """, (MaNV, NgayChamCong, GioVao, GioRa, TrangThai))

            conn.commit()
            flash("Đã thêm bản ghi chấm công mới!", "success")
            return redirect(url_for("attendance_report"))
        except Exception as e:
            flash(f"Lỗi khi thêm chấm công: {e}", "error")
        finally:
            conn.close()

    # Danh sách nhân viên đang hoạt động
    cursor.execute("SELECT MaNV, HoTen FROM NhanVien WHERE TrangThai=1")
    employees = cursor.fetchall()
    conn.close()
    return render_template("attendance_add.html", employees=employees)


# SỬA CHẤM CÔNG

@app.route("/attendance/edit/<int:id>", methods=["GET", "POST"])
@require_role("admin")
def edit_attendance(id):
    conn = get_sql_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        try:
            GioVao = request.form["GioVao"]
            GioRa = request.form.get("GioRa") or None
            TrangThai = int(request.form["TrangThai"])

            #Quan trọng: Lấy đúng tên field là MaCa (mã ca), KHÔNG phải CaLam (nhãn)
            MaCa = request.form.get("MaCa") or None

            # Nếu form không chọn mã ca → giữ nguyên mã ca cũ (tránh set rỗng gây lỗi FK)
            if MaCa is None or MaCa.strip() == "":
                cursor.execute("SELECT MaCa FROM ChamCong WHERE MaChamCong = ?", (id,))
                row_ma = cursor.fetchone()
                MaCa = row_ma[0] if row_ma else None

            # Validate MaCa có tồn tại trong CaLamViec
            if MaCa:
                cursor.execute("SELECT 1 FROM CaLamViec WHERE MaCa = ?", (MaCa,))
                if cursor.fetchone() is None:
                    flash("Mã ca không hợp lệ. Vui lòng chọn lại.", "error")
                    conn.close()
                    return redirect(url_for("attendance_edit", id=id))

            # Cập nhật dữ liệu
            cursor.execute("""
                UPDATE ChamCong
                SET GioVao = ?, GioRa = ?, TrangThai = ?, MaCa = ?
                WHERE MaChamCong = ?
            """, (GioVao, GioRa, TrangThai, MaCa, id))

            conn.commit()
            flash("Đã cập nhật bản ghi chấm công!", "info")
            conn.close()
            return redirect(url_for("attendance_report"))

        except Exception as e:
            conn.rollback()
            flash(f"Lỗi khi cập nhật: {e}", "error")
            conn.close()
            return redirect(url_for("attendance_report"))

    # ---------- GET: lấy bản ghi + danh sách ca ----------
    cursor.execute("""
        SELECT 
            CC.MaChamCong, CC.MaNV, NV.HoTen, PB.TenPB,
            CC.NgayChamCong, CC.GioVao, CC.GioRa, CC.TrangThai,
            CC.MaCa,                                 -- LẤY ĐÚNG MÃ CA HIỆN TẠI
            KM.DuongDanAnh,
            CASE 
                WHEN DATEPART(HOUR, CC.GioVao) BETWEEN 5 AND 11 THEN N'Ca sáng'
                WHEN DATEPART(HOUR, CC.GioVao) BETWEEN 11 AND 17 THEN N'Ca chiều'
                WHEN DATEPART(HOUR, CC.GioVao) BETWEEN 17 AND 23 THEN N'Ca tối'
                ELSE N'Không xác định'
            END AS CaLamNhanh                         -- chỉ để hiển thị tham khảo
        FROM ChamCong CC
        LEFT JOIN NhanVien NV ON CC.MaNV = NV.MaNV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        LEFT JOIN KhuonMat KM ON NV.MaNV = KM.MaNV
        WHERE CC.MaChamCong = ?
    """, (id,))
    row = cursor.fetchone()

    # Lấy danh sách ca hợp lệ cho dropdown
    cursor.execute("""
        SELECT MaCa, TenCa, 
               FORMAT(GioBatDau, 'HH:mm') + N' - ' + FORMAT(GioKetThuc, 'HH:mm') AS KhungGio
        FROM CaLamViec
        ORDER BY MaCa
    """)
    shifts = cursor.fetchall()

    # Cần lấy description trước khi đóng kết nối
    cols_main = [c[0] for c in cursor.description]  # tạm cho shifts, sẽ không dùng
    conn.close()

    if not row:
        flash("Không tìm thấy bản ghi chấm công.", "error")
        return redirect(url_for("attendance_report"))

    # Tạo dict cho record
    # Lưu ý: muốn lấy tên cột của SELECT bản ghi, ta rebuild theo SELECT ở trên:
    record_cols = [
        "MaChamCong","MaNV","HoTen","TenPB",
        "NgayChamCong","GioVao","GioRa","TrangThai",
        "MaCa","DuongDanAnh","CaLamNhanh"
    ]
    record = dict(zip(record_cols, row))

    avatar_path = record.get("DuongDanAnh")
    record["Avatar"] = "/" + avatar_path.replace("\\", "/") if (avatar_path and avatar_path.strip()) else "/static/photos/default.jpg"

    # Chuẩn hóa shifts thành list dict cho Jinja
    shift_list = [{"MaCa": s[0], "TenCa": s[1], "KhungGio": s[2]} for s in shifts]

    return render_template("attendance_edit.html", record=record, shifts=shift_list)

# XÓA CHẤM CÔNG

# ============================================================
# 🧹 XÓA MỀM 1 BẢN GHI CHẤM CÔNG
# ============================================================
@app.route("/attendance/delete/<int:id>", methods=["POST"])
@require_role("admin")
def delete_attendance(id):
    conn = get_sql_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE ChamCong
            SET DaXoa = 0
            WHERE MaChamCong = ?
        """, (id,))
        conn.commit()
        flash("🗑️ Đã xóa mềm bản ghi chấm công!", "warning")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa mềm: {e}", "error")
    finally:
        conn.close()
    return redirect(url_for("attendance_report"))

# ============================================================
# 🧹 XÓA MỀM NHIỀU BẢN GHI CHẤM CÔNG
# ============================================================
@app.route("/attendance/delete_multiple", methods=["POST"])
@require_role("admin")
def delete_multiple_attendance():
    selected_ids = request.form.getlist("selected_attendance")

    if not selected_ids:
        flash("⚠️ Chưa chọn bản ghi chấm công nào để xóa!", "warning")
        return redirect(url_for("attendance_report"))

    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        for ma_cc in selected_ids:
            # Lấy thông tin bản ghi trước khi xóa
            cursor.execute("""
                SELECT MaNV, NgayChamCong, GioVao, GioRa, TrangThai
                FROM ChamCong
                WHERE MaChamCong = ?
            """, (ma_cc,))
            old_data = cursor.fetchone()

            if not old_data:
                continue

            # 🔹 Xóa mềm (DaXoa = 0)
            cursor.execute("""
                UPDATE ChamCong
                SET DaXoa = 0
                WHERE MaChamCong = ?
            """, (ma_cc,))

            # 🔹 Ghi log thay đổi
            username = session.get("username", "Hệ thống")
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi, 
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "ChamCong",
                ma_cc,
                "Xóa mềm",
                "DaXoa",
                "1",  # Giá trị cũ (đang hoạt động)
                "0",  # Giá trị mới (đã xóa)
                username
            ))

        conn.commit()
        flash(f"🗑️ Đã xóa mềm {len(selected_ids)} bản ghi chấm công!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa mềm chấm công: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("attendance_report"))


# ============================================================
# 🔁 KHÔI PHỤC 1 BẢN GHI CHẤM CÔNG
# ============================================================
@app.route("/attendance/restore/<int:id>", methods=["POST"])
@require_role("admin")
def restore_attendance(id):
    conn = get_sql_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE ChamCong
            SET DaXoa = 1
            WHERE MaChamCong = ?
        """, (id,))
        conn.commit()
        flash("✅ Đã khôi phục bản ghi chấm công!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục: {e}", "error")
    finally:
        conn.close()

    # ✅ Quay lại tab Chấm công trong deleted_records.html
    return redirect(url_for("deleted_attendance"))

# ============================================================
# ============================================================
# 🔄 KHÔI PHỤC NHIỀU BẢN GHI CHẤM CÔNG
# ============================================================
@app.route("/attendance/restore_multiple", methods=["POST"])
@require_role("admin")
def restore_multiple_attendance():
    selected_ids = request.form.getlist("selected_ids")

    if not selected_ids:
        flash("⚠️ Chưa chọn bản ghi nào để khôi phục!", "warning")
        return redirect(url_for("deleted_attendance"))

    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        for ma_cc in selected_ids:
            # 🔹 Kiểm tra bản ghi trước khi khôi phục
            cursor.execute("""
                SELECT MaNV, NgayChamCong, DaXoa
                FROM ChamCong
                WHERE MaChamCong = ?
            """, (ma_cc,))
            record = cursor.fetchone()

            if not record:
                continue

            ma_nv, ngay, daxoa = record

            if daxoa == 1:
                # Đã khôi phục rồi, bỏ qua
                continue

            # 🔹 Khôi phục (DaXoa = 1)
            cursor.execute("""
                UPDATE ChamCong
                SET DaXoa = 1
                WHERE MaChamCong = ?
            """, (ma_cc,))

            # 🔹 Ghi log khôi phục
            username = session.get("username", "Hệ thống")
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "ChamCong",
                ma_cc,
                "Khôi phục",
                "DaXoa",
                "0", "1",  # Từ đã xóa → hoạt động
                username
            ))

        conn.commit()
        flash(f"✅ Đã khôi phục {len(selected_ids)} bản ghi chấm công!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("deleted_attendance"))

@app.route("/attendance/deleted")
@require_role("admin")
def deleted_attendance():
    """Hiển thị danh sách chấm công đã xóa - dùng riêng (hoặc tái sử dụng cho tab gộp)."""
    from datetime import datetime, time
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                cc.MaChamCong,
                ISNULL(cc.MaNV, nv.MaNV) AS MaNV,
                nv.HoTen,
                pb.TenPB,
                clv.TenCa,
                cc.NgayChamCong,
                cc.GioVao,
                cc.GioRa,
                cc.TrangThai

            FROM ChamCong cc
            JOIN NhanVien nv ON cc.MaNV = nv.MaNV
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            LEFT JOIN CaLamViec clv ON cc.MaCa = clv.MaCa
            WHERE cc.DaXoa = 0
            ORDER BY cc.NgayChamCong DESC
        """)
        rows = cursor.fetchall()

        def format_time(value):
            """Chỉ lấy phần giờ:phút:giây, bỏ ngày 1900."""
            if not value:
                return "—"
            if isinstance(value, (datetime, time)):
                return value.strftime("%H:%M:%S")
            val = str(value)
            if " " in val:
                val = val.split(" ")[-1]
            return val.replace("1900-01-01", "").strip() or "—"

        deleted_attendance = []
        for ma_cham_cong, ma_nv, ho_ten, ten_pb, ten_ca, ngay, gio_vao, gio_ra, trang_thai in rows:
            gio_vao_txt, gio_ra_txt = format_time(gio_vao), format_time(gio_ra)
            trang_thai = int(trang_thai or 0)

            if trang_thai == 1:
                status_text, status_class = "Đúng giờ", "bg-success"
            elif trang_thai == 2:
                status_text, status_class = "Đi muộn", "bg-warning text-dark"
            elif trang_thai == 0:
                status_text, status_class = "Vắng", "bg-danger"
            else:
                status_text, status_class = "Không xác định", "bg-secondary"

            deleted_attendance.append({
                "MaChamCong": str(ma_cham_cong),
                "MaNV": str(ma_nv) if ma_nv else "—",
                "HoTen": ho_ten or "—",
                "TenPB": ten_pb or "—",
                "TenCa": ten_ca or "—",
                "NgayChamCong": (
                    ngay.strftime("%Y-%m-%d") if isinstance(ngay, datetime)
                    else str(ngay)[:10] if ngay else ""
                ),
                "GioVao": gio_vao_txt,
                "GioRa": gio_ra_txt,
                "TrangThai": trang_thai,
                "TrangThaiText": status_text,
                "StatusClass": status_class
            })

    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách chấm công đã xóa: {e}", "error")
        deleted_attendance = []
    finally:
        conn.close()

    return render_template(
        "deleted_records.html",
        active_tab="attendance",
        deleted_attendance=deleted_attendance
    )


# =============================================
# HÀM TÍNH LƯƠNG CHO 1 NHÂN VIÊN
# =============================================
from datetime import datetime, date, time


# 1️⃣ HÀM CHUẨN CHUYỂN GIỜ & TÍNH LƯƠNG CHUNG
# ============================================================
def to_datetime(val):
    """Chuyển string/time/datetime về datetime hợp lệ."""
    if isinstance(val, datetime): 
        return val
    if isinstance(val, time): 
        return datetime.combine(date.today(), val)
    if isinstance(val, str):
        val = val.split('.')[0].strip()
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(val, fmt)
            except:
                pass
    return None

def tinh_luong_nv(cursor, ma_nv, thangnam, nguoi_tinh, save_to_db=True, return_detail=False):
    current_month = thangnam.month
    current_year = thangnam.year

    # --- Lấy chức vụ ---
    cursor.execute("SELECT ChucVu FROM NhanVien WHERE MaNV=?", (ma_nv,))
    row = cursor.fetchone()
    chucvu = (row[0] or "").lower() if row else ""

    # --- Hệ số chức vụ ---
    if "trưởng phòng" in chucvu:
        he_so = 1.2
    elif "phó phòng" in chucvu:
        he_so = 1.1
    elif "thực tập" in chucvu or "intern" in chucvu:
        he_so = 0.9
    else:
        he_so = 1.0  # nhân viên

    # --- Lấy dữ liệu chấm công ---
    cursor.execute("""
        SELECT 
            ISNULL(CC.MaCa, CLV.MaCa) AS MaCa,
            CC.NgayChamCong, 
            CC.GioVao, CC.GioRa, 
            CLV.GioBatDau, CLV.GioKetThuc, 
            ISNULL(CLV.TenCa, N'Không xác định') AS TenCa
        FROM ChamCong CC
        LEFT JOIN CaLamViec CLV ON CC.MaCa = CLV.MaCa
        WHERE CC.MaNV=? AND MONTH(CC.NgayChamCong)=? AND YEAR(CC.NgayChamCong)=?
    """, (ma_nv, current_month, current_year))
    cham_cong_records = cursor.fetchall()

    if not cham_cong_records:
        return (0, 0, []) if return_detail else (0, 0)

    tong_tien, tong_gio, chi_tiet_ca = 0, 0, []

    # --- Chuyển đổi thời gian ---
    def to_datetime(val):
        if isinstance(val, datetime):
            return val
        if isinstance(val, time):
            return datetime.combine(date.today(), val)
        if isinstance(val, str):
            val = val.split('.')[0].strip()
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(val, fmt)
                except:
                    pass
        return None

    # --- Duyệt từng bản ghi ---
    for ma_ca, ngay, gio_vao, gio_ra, gio_bd, gio_kt, ten_ca in cham_cong_records:
        if isinstance(ngay, str):
            try:
                ngay_obj = datetime.strptime(ngay.split(" ")[0], "%Y-%m-%d")
            except:
                ngay_obj = datetime.today()
        else:
            ngay_obj = ngay

        gio_vao, gio_ra, gio_bd, gio_kt = map(to_datetime, [gio_vao, gio_ra, gio_bd, gio_kt])
        if not all([gio_vao, gio_ra, gio_bd, gio_kt]):
            continue
        if gio_ra < gio_vao:
            gio_ra += timedelta(days=1)

        # --- Tính số giờ làm & phút trễ ---
        so_gio = (gio_ra - gio_vao).total_seconds() / 3600
        di_tre = max((gio_vao - gio_bd).total_seconds() / 60, 0)
        gio_chuan = (gio_kt - gio_bd).total_seconds() / 3600

        # --- Loại ca ---
        ca_str = (ten_ca or ma_ca).lower()
        la_ca_toi = any(x in ca_str for x in ["tối", "dem", "đêm", "ca 3", "ca3"])
        muc_ca_nv = 800_000 if la_ca_toi else 500_000
        muc_gio_nv = 150_000 if la_ca_toi else 100_000

        # --- Phạt đi trễ ---
        phat, ly_do = 0, ""
        gio_tinh_luong = so_gio  # mặc định tính toàn bộ giờ làm

        if di_tre <= 5:
            ly_do = "Đúng giờ hoặc trễ ≤5p"
        elif di_tre <= 30:
            phat = 50_000
            ly_do = f"Đi trễ {int(di_tre)}p (phạt 50k)"
        elif di_tre <= 60:
            phat = 100_000
            ly_do = f"Đi trễ {int(di_tre)}p (phạt 100k)"
        else:
            # Trễ >60p → chỉ tính nửa số giờ làm
            gio_tinh_luong = so_gio / 2
            ly_do = f"Đi trễ {int(di_tre)}p (chỉ tính 50% giờ làm: {round(gio_tinh_luong,2)}h)"

        # --- Tính tiền ---
        if gio_tinh_luong >= gio_chuan - 0.1:  # đủ full ca
            tien = muc_ca_nv * he_so - phat
            ly_do = (ly_do + "; " if ly_do else "") + "Làm đủ ca"
        elif gio_tinh_luong < 4:  # chưa đủ 4 tiếng
            tien = gio_tinh_luong * muc_gio_nv * he_so - phat
            ly_do = (ly_do + "; " if ly_do else "") + "Làm chưa đủ 4 tiếng"
        elif gio_tinh_luong >= 4.5:  # làm >4h30
            tien_full = muc_ca_nv * he_so
            them_gio = gio_tinh_luong - gio_chuan
            tien = tien_full + (them_gio * 100_000 * he_so) - phat
            ly_do = (ly_do + "; " if ly_do else "") + f"Làm thêm {round(them_gio,2)}h"
        else:
            # Làm giữa 4h và đủ ca
            ty_le = gio_tinh_luong / gio_chuan
            tien = muc_ca_nv * ty_le * he_so - phat
            ly_do = (ly_do + "; " if ly_do else "") + "Làm chưa đủ ca"

        tong_tien += tien
        tong_gio += so_gio

        if return_detail:
            chi_tiet_ca.append({
                "NgayChamCong": ngay_obj.strftime("%d/%m/%Y"),
                "Ca": ten_ca or ma_ca,
                "GioVao": gio_vao.strftime("%H:%M"),
                "GioRa": gio_ra.strftime("%H:%M"),
                "SoGio": round(so_gio, 2),
                "GioTinhLuong": round(gio_tinh_luong, 2),
                "HeSo": he_so,
                "Tien": round(tien, 0),
                "LyDoTru": ly_do or "—"
            })

    # --- Lưu DB ---
    if save_to_db:
        cursor.execute("""
            DELETE FROM Luong 
            WHERE MaNV=? AND MONTH(ThangNam)=? AND YEAR(ThangNam)=?
        """, (ma_nv, current_month, current_year))
        cursor.execute("""
            INSERT INTO Luong (MaNV, ThangNam, SoGioLam, TongTien, TrangThai, NguoiTinhLuong, NgayTinhLuong)
            VALUES (?, ?, ?, ?, 1, ?, GETDATE())
        """, (ma_nv, thangnam, tong_gio, tong_tien, nguoi_tinh))

    return (round(tong_gio, 2), round(tong_tien, 0), chi_tiet_ca) if return_detail else (round(tong_gio, 2), round(tong_tien, 0))


@app.route("/salary")
@require_role("admin")
def salary_view():
    conn = get_sql_connection()
    cursor = conn.cursor()

    current_year = datetime.now().year
    current_month = datetime.now().month

    # 🟢 Tổng số nhân viên đang hoạt động
    cursor.execute("""
        SELECT COUNT(*) 
        FROM NhanVien 
        WHERE TrangThai = 1
    """)
    total_employees = cursor.fetchone()[0] or 0

    # 🟢 Số nhân viên đã có lương tháng này (chỉ tính nhân viên còn hoạt động)
    cursor.execute("""
        SELECT COUNT(DISTINCT L.MaNV)
        FROM Luong L
        JOIN NhanVien NV ON L.MaNV = NV.MaNV
        WHERE MONTH(L.ThangNam)=? 
          AND YEAR(L.ThangNam)=? 
          AND L.DaXoa = 1
          AND L.TrangThai = 1
          AND NV.TrangThai = 1
    """, (current_month, current_year))
    total_salaried = cursor.fetchone()[0] or 0

    # 🟢 Số nhân viên chưa tính
    total_unsalaried = max(total_employees - total_salaried, 0)

    # 🟢 Tổng quỹ lương tháng này (chỉ tính lương hợp lệ của nhân viên còn hoạt động)
    cursor.execute("""
        SELECT SUM(L.TongTien)
        FROM Luong L
        JOIN NhanVien NV ON L.MaNV = NV.MaNV
        WHERE MONTH(L.ThangNam)=? 
          AND YEAR(L.ThangNam)=? 
          AND L.DaXoa = 1
          AND L.TrangThai = 1
          AND NV.TrangThai = 1
    """, (current_month, current_year))
    total_salary = cursor.fetchone()[0] or 0

    # 🟢 Danh sách nhân viên đang hoạt động + lương còn hiệu lực
    cursor.execute("""
        SELECT 
            NV.MaNV,
            NV.HoTen,
            PB.TenPB AS PhongBan,
            ISNULL(L.SoGioLam, 0) AS SoGioLam,
            ISNULL(L.TongTien, 0) AS TongTien,
            ISNULL(L.TrangThai, 0) AS TrangThai,
            ISNULL(L.DaXoa, 1) AS DaXoa
        FROM NhanVien NV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        LEFT JOIN Luong L 
            ON NV.MaNV = L.MaNV 
            AND MONTH(L.ThangNam)=? 
            AND YEAR(L.ThangNam)=?
            AND (L.DaXoa = 1 OR L.DaXoa IS NULL)
        WHERE NV.TrangThai = 1
        ORDER BY NV.MaNV
    """, (current_month, current_year))

    cols = [c[0] for c in cursor.description]
    salaries = [dict(zip(cols, row)) for row in cursor.fetchall()]

    conn.close()

    # 🧾 Render kết quả ra giao diện
    return render_template(
        "salary.html",
        total_employees=total_employees,
        total_salaried=total_salaried,
        total_unsalaried=total_unsalaried,
        total_salary=total_salary,
        salaries=salaries,
        current_month=current_month,
        current_year=current_year
    )



# ============================================================
# 3️⃣ TÍNH LƯƠNG TOÀN BỘ
# ============================================================
@app.route("/calculate_salary")
@require_role("admin")
def calculate_all_salary():
    conn = get_sql_connection()
    cursor = conn.cursor()

    today = datetime.now()
    thangnam = datetime(today.year, today.month, 1)
    nguoi_tinh = session.get("username", "Admin")

    try:
        cursor.execute("SELECT MaNV FROM NhanVien")
        nhanvien = cursor.fetchall()
        if not nhanvien:
            return jsonify({"success": False, "message": "⚠️ Không có nhân viên nào trong hệ thống."})

        da_tinh = 0
        for (ma_nv,) in nhanvien:
            try:
                tinh_luong_nv(cursor, ma_nv, thangnam, nguoi_tinh)
                da_tinh += 1
            except Exception as e:
                print(f"Lỗi khi tính lương {ma_nv}: {e}")

        conn.commit()
        return jsonify({"success": True, "message": f"✅ Đã tính lương cho {da_tinh}/{len(nhanvien)} nhân viên!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": f"❌ Lỗi khi tính lương: {str(e)}"})
    finally:
        cursor.close()
        conn.close()

# ============================================================
# 🔹 TÍNH LƯƠNG RIÊNG CHO 1 NHÂN VIÊN
# ============================================================
@app.route("/calculate_salary/<ma_nv>")
@require_role("admin")
def calculate_salary_for_one(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()

    today = datetime.now()
    thangnam = datetime(today.year, today.month, 1)
    nguoi_tinh = session.get("username", "Admin")

    try:
        tong_gio, tong_tien, _ = tinh_luong_nv(
            cursor, ma_nv, thangnam, nguoi_tinh, save_to_db=True, return_detail=True
        )
        conn.commit()
        return jsonify({
            "success": True,
            "message": f"✅ Đã tính lương cho {ma_nv}: {tong_gio:.2f} giờ, {tong_tien:,.0f} VND"
        })
    except Exception as e:
        conn.rollback()
        return jsonify({
            "success": False,
            "message": f"❌ Lỗi khi tính lương {ma_nv}: {str(e)}"
        })
    finally:
        cursor.close()
        conn.close()

# ============================================================
# 4️⃣ CHI TIẾT LƯƠNG MỖI NHÂN VIÊN
# ============================================================
@app.route("/salary/<ma_nv>")
@require_role("admin")
def salary_detail(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()
    now = datetime.now()
    thangnam = datetime(now.year, now.month, 1)

    cursor.execute("""
        SELECT NV.MaNV, NV.HoTen, NV.ChucVu, PB.TenPB
        FROM NhanVien NV
        LEFT JOIN PhongBan PB ON NV.MaPB=PB.MaPB
        WHERE NV.MaNV=?
    """, (ma_nv,))
    emp = cursor.fetchone()
    if not emp:
        conn.close()
        return f"<h3>❌ Không tìm thấy nhân viên {ma_nv}</h3>"

    # ⚙️ Xem chi tiết chỉ tính, không ghi DB
    tong_gio, tong_tien, records = tinh_luong_nv(
    cursor, ma_nv, thangnam, "Xem chi tiết", save_to_db=False, return_detail=True
)
    conn.close()

    # --- Gán biểu tượng ---
    chucvu = (emp[2] or "").lower()
    if "trưởng phòng" in chucvu:
        role_label, role_icon = "Trưởng phòng", "fa-star text-warning"
    elif "phó phòng" in chucvu:
        role_label, role_icon = "Phó phòng", "fa-crown text-info"
    elif "thực tập" in chucvu or "intern" in chucvu:
        role_label, role_icon = "Thực tập sinh", "fa-user-graduate text-secondary"
    else:
        role_label, role_icon = "Nhân viên", "fa-user text-primary"

    return render_template("salary_detail.html",
        emp=emp,
        records=records,
        tong_gio=tong_gio,
        tong_tien=tong_tien,
        role_label=role_label,
        role_icon=role_icon,
        current_month=now.month,
        current_year=now.year
    )

# ============================================================
# ❌ XÓA MỀM 1 BẢN GHI LƯƠNG THEO MÃ NHÂN VIÊN
# ============================================================
@app.route("/salary/delete/<ma_nv>", methods=["POST"])
@require_role("admin")
def delete_salary(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        cursor.execute("""
            UPDATE Luong
            SET DaXoa = 0
            WHERE MaNV = ?
        """, (ma_nv,))

        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("Luong", ma_nv, "Xóa mềm", "DaXoa", 1, 0, username))

        conn.commit()
        flash(f"🗑️ Đã xóa mềm lương của nhân viên {ma_nv}!", "warning")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa mềm: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("salary_view"))


# ============================================================
# 🧹 XÓA MỀM NHIỀU BẢN GHI LƯƠNG
# ============================================================
@app.route("/salary/delete-multiple", methods=["POST"])
@require_role("admin")
def delete_multiple_salary():
    ma_nv_list = request.form.getlist("selected_salaries")
    if not ma_nv_list:
        flash("⚠️ Chưa chọn nhân viên nào để xóa lương!", "warning")
        return redirect(url_for("salary_view"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for ma_nv in ma_nv_list:
            cursor.execute("UPDATE Luong SET DaXoa = 0 WHERE MaNV = ?", (ma_nv,))
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, ("Luong", ma_nv, "Xóa mềm", "DaXoa", 1, 0, username))
        conn.commit()
        flash(f"🗑️ Đã xóa mềm {len(ma_nv_list)} bản ghi lương!", "warning")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa nhiều: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("salary_view"))


# ============================================================
# ♻️ KHÔI PHỤC 1 BẢN GHI LƯƠNG
# ============================================================
@app.route("/salary/restore/<int:id>", methods=["POST"])
@require_role("admin")
def restore_salary(id):
    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        cursor.execute("UPDATE Luong SET DaXoa = 1 WHERE MaLuong = ?", (id,))
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("Luong", id, "Khôi phục", "DaXoa", 0, 1, username))

        conn.commit()
        flash("✅ Đã khôi phục bản ghi lương!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("deleted_salaries"))


# ============================================================
# 🔁 KHÔI PHỤC NHIỀU BẢN GHI LƯƠNG
# ============================================================
@app.route("/salary/restore_multiple", methods=["POST"])
@require_role("admin")
def restore_multiple_salaries():
    ids = request.form.getlist("selected_salaries")
    if not ids:
        flash("⚠️ Chưa chọn bản ghi nào để khôi phục!", "warning")
        return redirect(url_for("deleted_salaries"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for salary_id in ids:
            cursor.execute("UPDATE Luong SET DaXoa = 1 WHERE MaLuong = ?", (salary_id,))
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, ("Luong", salary_id, "Khôi phục nhiều", "DaXoa", 0, 1, username))
        conn.commit()
        flash(f"♻️ Đã khôi phục {len(ids)} bản ghi lương!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục nhiều: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("deleted_salaries"))


# ============================================================
# 📋 DANH SÁCH LƯƠNG ĐÃ XÓA
# ============================================================
@app.route("/salary/deleted")
@require_role("admin")
def deleted_salaries():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                L.MaLuong,
                NV.MaNV,
                NV.HoTen,
                PB.TenPB,
                L.SoGioLam,
                L.TongTien,
                L.ThangNam
            FROM Luong L
            JOIN NhanVien NV ON L.MaNV = NV.MaNV
            LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
            WHERE L.DaXoa = 0
            ORDER BY L.ThangNam DESC
        """)
        rows = cursor.fetchall()
        cols = [c[0] for c in cursor.description]
        deleted_salaries = [dict(zip(cols, row)) for row in rows]
    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách lương đã xóa: {e}", "error")
        deleted_salaries = []
    finally:
        conn.close()

    # ✅ Đặt đúng tên tab: 'salaries'
    return render_template(
        "deleted_records.html",
        deleted_salaries=deleted_salaries,
        active_tab="salaries"   # ✅ Sửa ở đây
    )

# Lịch sử thay đổi

@app.route("/history")
@require_role("admin")
def history():
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy tham số từ form ---
    selected_table = request.args.get("table")
    selected_action = request.args.get("action")
    keyword_user = request.args.get("user", "").strip()

    # --- Câu truy vấn chính ---
    base_query = """
        SELECT 
            ls.*, 
            COALESCE(tk.TenDangNhap, ls.NguoiThucHien) AS TenDangNhap
        FROM LichSuThayDoi ls
        LEFT JOIN TaiKhoan tk 
            ON TRY_CAST(ls.NguoiThucHien AS INT) = tk.MaTK
    """

    filters = []
    params = []

    # --- Lọc theo bảng ---
    if selected_table:
        filters.append("ls.TenBang = ?")
        params.append(selected_table)

    # --- Lọc theo hành động ---
    if selected_action:
        filters.append("ls.HanhDong = ?")
        params.append(selected_action)

    # --- Lọc theo người thực hiện (LIKE) ---
    if keyword_user:
        filters.append("(tk.TenDangNhap LIKE ? OR ls.NguoiThucHien LIKE ?)")
        like_pattern = f"%{keyword_user}%"
        params.extend([like_pattern, like_pattern])

    if filters:
        base_query += " WHERE " + " AND ".join(filters)

    base_query += " ORDER BY ls.ThoiGian DESC"

    cursor.execute(base_query, params)
    rows = cursor.fetchall()

    # --- Danh sách bảng và hành động (thêm “Xem chi tiết”) ---
    cursor.execute("SELECT DISTINCT TenBang FROM LichSuThayDoi ORDER BY TenBang")
    table_names = [r[0] for r in cursor.fetchall()]

    cursor.execute("""
        SELECT DISTINCT HanhDong 
        FROM LichSuThayDoi 
        WHERE HanhDong IN (N'Thêm', N'Sửa', N'Xóa', N'Xem chi tiết')
        ORDER BY HanhDong
    """)
    action_names = [r[0] for r in cursor.fetchall()]

    conn.close()
    return render_template(
        "history.html",
        histories=rows,
        tables=table_names,
        actions=action_names,
        selected_table=selected_table,
        selected_action=selected_action,
        keyword_user=keyword_user
    )

@app.route("/settings", endpoint='settings')
@require_role("admin")
def settings_view():
    return "<h1>Trang Cài đặt (Settings)</h1>"

from flask import send_from_directory

@app.route('/photos/<path:filename>')
def serve_photos(filename):
    """Cho phép Flask hiển thị ảnh từ thư mục photos/"""
    import os
    photo_dir = os.path.join(os.getcwd(), 'photos')  # đường dẫn tuyệt đối
    return send_from_directory(photo_dir, filename)

@app.route("/export_report/word")
def export_report_word():
    # Lấy dữ liệu thống kê
    total_employees = 6
    total_departments = 4
    attendance_rate = "96.5%"
    avg_hours = 4
    total_shifts = 1
    total_salary = 0

    # Tạo file Word
    doc = Document()
    doc.add_heading("BÁO CÁO TỔNG QUAN HỆ THỐNG", level=1)
    doc.add_paragraph(f"Tổng nhân viên: {total_employees}")
    doc.add_paragraph(f"Tổng phòng ban: {total_departments}")
    doc.add_paragraph(f"Tỉ lệ chấm công: {attendance_rate}")
    doc.add_paragraph(f"Giờ trung bình/Tuần: {avg_hours}")
    doc.add_paragraph(f"Tổng số ca: {total_shifts}")
    doc.add_paragraph(f"Tổng lương: {total_salary}")

    # Lưu ra bộ nhớ tạm
    file_stream = io.BytesIO()
    doc.save(file_stream)
    file_stream.seek(0)

    return send_file(
        file_stream,
        as_attachment=True,
        download_name="BaoCaoTongQuan.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

@app.route("/export_report/excel")
@require_role("admin")
def export_report_excel():
    wb = Workbook()
    ws = wb.active
    ws.title = "Báo cáo tổng quan"

    ws.append(["Chỉ tiêu", "Giá trị"])
    ws.append(["Tổng nhân viên", 6])
    ws.append(["Tổng phòng ban", 4])
    ws.append(["Tỉ lệ chấm công", "96.5%"])
    ws.append(["Giờ TB/Tuần", 4])
    ws.append(["Tổng số ca", 1])
    ws.append(["Tổng lương", 0])

    file_stream = io.BytesIO()
    wb.save(file_stream)
    file_stream.seek(0)

    return send_file(
        file_stream,
        as_attachment=True,
        download_name="BaoCaoTongQuan.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

def cap_nhat_vang_va_phep():
    conn = get_sql_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO ChamCong (MaNV, MaLLV, MaCa, NgayChamCong, TrangThai, DaXoa, GhiChu)
        SELECT 
            llv.MaNV, llv.MaLLV, llv.MaCa, llv.NgayLam, 0, 1, N'Không chấm công'
        FROM LichLamViec llv
        LEFT JOIN ChamCong cc
            ON llv.MaNV = cc.MaNV 
           AND llv.MaCa = cc.MaCa 
           AND llv.NgayLam = cc.NgayChamCong
        WHERE cc.MaChamCong IS NULL 
          AND llv.NgayLam < CAST(GETDATE() AS DATE)
          AND llv.DaXoa = 1
    """)

    conn.commit()
    conn.close()
@app.route("/update_absences", methods=["POST"])
@require_role("admin")
def update_absences():
    try:
        cap_nhat_vang_va_phep()
        flash("✅ Đã cập nhật trạng thái VẮNG cho nhân viên chưa chấm công!", "success")
    except Exception as e:
        flash(f"❌ Lỗi khi cập nhật vắng: {e}", "error")
    return redirect(url_for("attendance_report"))


#NHÂN VIÊN
# TRANG CHÍNH CỦA NHÂN VIÊN

@app.route("/employee/dashboard")
def employee_dashboard():
    # Kiểm tra đăng nhập
    if "manv" not in session:
        return redirect(url_for("login"))

    ma_nv = session["manv"]

    conn = get_sql_connection()
    cursor = conn.cursor()

    # 1. Lấy thông tin nhân viên
    cursor.execute("""
        SELECT nv.MaNV, nv.HoTen, nv.Email, nv.NgaySinh, nv.ChucVu, nv.DiaChi, 
               pb.TenPB, nv.LuongGioCoBan
        FROM NhanVien nv
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        WHERE nv.MaNV = ?
    """, (ma_nv,))
    row = cursor.fetchone()
    nhanvien = dict(zip([col[0] for col in cursor.description], row)) if row else {}

    # 2. Lấy thông tin ca làm việc của nhân viên
    cursor.execute("""
        SELECT clv.MaCa, clv.TenCa, clv.GioBatDau, clv.GioKetThuc, clv.HeSo, hsl.DonGia
        FROM LichLamViec llv
        JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
        LEFT JOIN HeSoLuong hsl ON clv.MaHSL = hsl.MaHSL
        WHERE llv.MaNV = ?
    """, (ma_nv,))
    calamviec = [dict(zip([col[0] for col in cursor.description], r)) for r in cursor.fetchall()]

    # 3. Lịch sử chấm công
    cursor.execute("""
        SELECT MaChamCong, NgayChamCong, GioVao, GioRa, TrangThai
        FROM ChamCong
        WHERE MaNV = ?
        ORDER BY NgayChamCong DESC
    """, (ma_nv,))
    chamcong = [dict(zip([col[0] for col in cursor.description], r)) for r in cursor.fetchall()]

    # 4. Lịch sử hoạt động
    cursor.execute("""
        SELECT ThoiGian, TenBang, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi
        FROM LichSuThayDoi
        WHERE NguoiThucHien = ?
        ORDER BY ThoiGian DESC
    """, (session["hoten"],))
    lichsu = [dict(zip([col[0] for col in cursor.description], r)) for r in cursor.fetchall()]

    conn.close()

    return render_template(
        "employee_dashboard.html",
        nhanvien=nhanvien,
        calamviec=calamviec,
        chamcong=chamcong,
        lichsu=lichsu
    )

# Trang xem ca làm của nhân viên

@app.route("/employee/shifts")

def employee_shifts():
    if "manv" not in session:
        return redirect(url_for("login"))

    ma_nv = session["manv"]

    conn = get_sql_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT clv.MaCa, clv.TenCa, clv.GioBatDau, clv.GioKetThuc, clv.HeSo, hsl.DonGia
        FROM LichLamViec llv
        JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
        LEFT JOIN HeSoLuong hsl ON clv.MaHSL = hsl.MaHSL
        WHERE llv.MaNV = ?
    """, (ma_nv,))

    calamviec = [dict(zip([col[0] for col in cursor.description], r)) for r in cursor.fetchall()]
    conn.close()

    return render_template("employee_shifts.html", calamviec=calamviec)

# Trang xem lịch sử chấm công của nhân viên

@app.route("/employee/attendance")
def employee_attendance():
    if "manv" not in session:
        return redirect(url_for("login"))

    ma_nv = session["manv"]
    conn = get_sql_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT NgayChamCong, GioVao, GioRa, TrangThai
        FROM ChamCong
        WHERE MaNV = ?
        ORDER BY NgayChamCong DESC
    """, (ma_nv,))
    chamcong = [dict(zip([col[0] for col in cursor.description], r)) for r in cursor.fetchall()]
    conn.close()

    return render_template("employee_attendance.html", chamcong=chamcong)

# Trang xem lịch sử hoạt động của nhân viên

@app.route("/employee/history")
def employee_history():
    if "manv" not in session:
        return redirect(url_for("login"))

    hoten = session["hoten"]

    conn = get_sql_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT ThoiGian, TenBang, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi
        FROM LichSuThayDoi
        WHERE NguoiThucHien = ?
        ORDER BY ThoiGian DESC
    """, (hoten,))
    lichsu = [dict(zip([col[0] for col in cursor.description], r)) for r in cursor.fetchall()]
    conn.close()

    return render_template("employee_history.html", lichsu=lichsu)

# Đăng xuất

@app.route("/logout")
def logout():
    session.clear()
    flash("Đã đăng xuất thành công!", "success")
    return redirect(url_for("login"))

# Trang thông tin nhân viên

@app.route("/employee/profile")
def employee_profile():
    if "role" not in session or session["role"].lower() != "nhanvien":
        flash("Chỉ nhân viên mới truy cập được trang này!", "warning")
        return redirect(url_for("login"))

    ma_nv = session.get("manv")

    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT nv.MaNV, nv.HoTen, nv.Email, nv.SDT, nv.NgaySinh, nv.DiaChi, 
               nv.ChucVu, pb.TenPB, km.DuongDanAnh
        FROM NhanVien nv
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat km ON nv.MaNV = km.MaNV
        WHERE nv.MaNV = ?
    """, (ma_nv,))
    emp = cursor.fetchone()
    conn.close()

    if not emp:
        flash("Không tìm thấy thông tin nhân viên!", "danger")
        return redirect(url_for("login"))

    fields = [col[0] for col in cursor.description]
    emp_dict = dict(zip(fields, emp))

    return render_template("employee_profile.html", employee=emp_dict)


# Run app
# ======================
if __name__ == "__main__":
    app.run(debug=True)


