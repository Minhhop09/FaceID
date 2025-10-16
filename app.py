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

# Trang chính

@app.route("/")
@app.route("/index")
def index():
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", username=session["username"])

# Trang đăng ký nhân viên

@app.route("/register", methods=["GET", "POST"])
def register():
    if "username" not in session:
        return redirect(url_for("login"))

    phongbans = get_phongbans()

    if request.method == "POST":
        # --- Lấy dữ liệu từ form ---
        hoten = request.form.get("HoTen", "").strip()
        email = request.form.get("Email", "").strip()
        sdt = request.form.get("SDT", "").strip()
        gioitinh_input = request.form.get("GioiTinh", "").strip().lower()
        ngaysinh = request.form.get("NgaySinh", "").strip()
        diachi = request.form.get("DiaChi", "").strip()
        ma_pb = request.form.get("PhongBan", "").strip()
        chucvu = request.form.get("ChucVu", "").strip()

        # --- Kiểm tra dữ liệu bắt buộc ---
        if not hoten or not email or not ma_pb:
            flash("Vui lòng điền đầy đủ thông tin bắt buộc!", "danger")
            return redirect(url_for("register"))

        gioitinh = 1 if gioitinh_input == "nam" else 0 if gioitinh_input == "nữ" else None
        if gioitinh is None:
            flash("Giới tính không hợp lệ. Vui lòng nhập 'Nam' hoặc 'Nữ'.", "danger")
            return redirect(url_for("register"))

        conn = get_connection()
        cursor = conn.cursor()

        try:
            # --- Sinh mã nhân viên ---
            ma_nv = generate_ma_nv(ma_pb)

            # --- Chuẩn bị dữ liệu ngày ---
            today_str = datetime.now().strftime("%Y-%m-%d")  # tránh lỗi SQLBindParameter
            ngay_sinh_str = ngaysinh if ngaysinh else None

            # --- Thêm nhân viên vào bảng NhanVien ---
            sql = """
                INSERT INTO NhanVien (
                    MaNV, HoTen, Email, SDT, GioiTinh, NgaySinh, DiaChi, MaPB, ChucVu,
                    TrangThai, NgayVaoLam, NgayNghiViec, NgayTao
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.execute(sql, (
                ma_nv, hoten, email, sdt, gioitinh, ngay_sinh_str, diachi, ma_pb, chucvu,
                1, today_str, None, today_str
            ))
            conn.commit()

            # --- Chụp ảnh và lưu ---
            image_path = capture_photo_and_save(ma_nv)
            if image_path:
                encode_and_save(ma_nv, image_path, conn)

                # Nếu bạn dùng cache khuôn mặt toàn hệ thống
                global known_encodings, known_ids, known_names
                known_encodings, known_ids, known_names = load_known_faces()

            flash("Nhân viên và FaceID đã được đăng ký thành công!", "success")

        except Exception as e:
            flash(f"Lỗi khi thêm nhân viên: {e}", "danger")

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
    if "username" not in session:
        return redirect(url_for("login"))
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

    # Kiểm tra theo nhân viên + ngày + ca
    cursor.execute("""
        SELECT GioVao, GioRa FROM ChamCong
        WHERE MaNV=? AND NgayChamCong=? AND MaCa=?
    """, (ma_nv, today, ma_ca))
    row = cursor.fetchone()

    if not row:
        if mode == "in":
            cursor.execute("""
                INSERT INTO ChamCong (MaNV, MaCa, NgayChamCong, GioVao, TrangThai)
                VALUES (?, ?, ?, ?, ?)
            """, (ma_nv, ma_ca, today, now_time, 1))
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
                    UPDATE ChamCong SET GioRa=?, TrangThai=2
                    WHERE MaNV=? AND NgayChamCong=? AND MaCa=?
                """, (now_time, ma_nv, today, ma_ca))
                conn.commit()
                flash(f"{ma_ca} - Ra ca lúc {now_time}", "success")

    conn.close()

    # Cập nhật lại thông tin cho đúng ca vừa thao tác
    update_current_employee(ma_nv, ma_ca)

    return redirect(url_for("attendance"))

    # 🔹 Cập nhật lại dữ liệu cho phần hiển thị bên phải
    update_current_employee(ma_nv)

    return redirect(url_for("attendance"))
@app.route("/current_employee")
def current_employee_api():
    return jsonify(current_employee if current_employee else {"error": "No employee"})

# Trang Admin

@app.route('/admin')
def admin_dashboard():
    if 'role' in session and session['role'] == 'admin':
        conn = get_sql_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM NhanVien")
        total_employees = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM PhongBan")
        total_departments = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM CaLamViec")
        total_shifts = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM TaiKhoan")
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

@app.route("/employees")
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
        WHERE 1=1
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
    cursor.execute("SELECT COUNT(*) FROM NhanVien")
    total_employees = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM PhongBan")
    total_departments = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM NhanVien WHERE ChucVu LIKE N'%Trưởng phòng%'")
    total_managers = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM NhanVien
        WHERE TRY_CONVERT(DATE, NgaySinh, 103) IS NOT NULL
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
def employee_detail(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy thông tin nhân viên đầy đủ ---
    cursor.execute("""
        SELECT 
            nv.MaNV,
            nv.HoTen,
            nv.Email,
            nv.SDT,
            nv.GioiTinh,
            nv.NgaySinh,
            nv.DiaChi,
            pb.TenPB AS TenPhongBan,
            nv.ChucVu,
            nv.TrangThai,
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

    # --- Xử lý ngày sinh ---
    raw_date = employee.get("NgaySinh")
    if raw_date:
        try:
            if isinstance(raw_date, str):
                employee["NgaySinh"] = datetime.strptime(raw_date[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
            else:
                employee["NgaySinh"] = raw_date.strftime("%d/%m/%Y")
        except Exception:
            employee["NgaySinh"] = raw_date
    else:
        employee["NgaySinh"] = "—"

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

    # --- Xử lý thời gian cập nhật ---
    employee["LastUpdated"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # --- Ghi log lịch sử ---
    cursor.execute("""
        INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, GiaTriMoi, NguoiThucHien)
        VALUES (?, ?, ?, ?, ?)
    """, ("NhanVien", ma_nv, "Xem chi tiết", employee["HoTen"], session.get("user_id")))

    conn.commit()
    conn.close()

    return render_template("employee_detail.html", employee=employee)


# Route thêm nhân viên

@app.route("/employees/add", methods=["GET", "POST"])
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
                flash(f"⚠️ Mã nhân viên {MaNV} đã tồn tại!", "error")
                conn.close()
                return redirect(url_for("employee_list"))

            # --- Thêm nhân viên ---
            cursor.execute("""
                INSERT INTO NhanVien (MaNV, HoTen, Email, SDT, GioiTinh, NgaySinh, MaPB, DiaChi, ChucVu, TrangThai, NgayTao)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, GETDATE())
            """, (MaNV, HoTen, Email, SDT, GioiTinh, NgaySinh, MaPB, DiaChi, ChucVu))
            conn.commit()
            print(f"✅ Đã thêm nhân viên {MaNV} vào bảng NhanVien.")
            conn.close()

            # --- Ghi log lịch sử ---
            conn = get_sql_connection()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO LichSuThayDoi (Bang, MaBanGhi, HanhDong, TruongThayDoi, DuLieuCu, DuLieuMoi, ThoiGian, NguoiThucHien)
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, ("NhanVien", MaNV, "THÊM", "Toàn bộ", "", f"{HoTen} - {ChucVu}", session.get("username", "admin")))
            conn.commit()
            conn.close()

            # --- Chụp ảnh ---
            print(f"📸 Đang chụp ảnh cho nhân viên: {MaNV}...")
            image_path = capture_photo_and_save(MaNV)

            if not image_path:
                flash("❌ Không chụp được ảnh khuôn mặt!", "error")
            else:
                flash("✅ Đã thêm nhân viên và lưu khuôn mặt thành công!", "success")

            return redirect(url_for("employee_list"))

        except Exception as e:
            print(f"❌ Lỗi khi thêm nhân viên: {e}")
            flash("❌ Lỗi khi thêm nhân viên. Vui lòng thử lại!", "error")
            if conn:
                conn.close()
            return redirect(url_for("employee_list"))

    # Nếu GET -> render form thêm
    return render_template("add_employee.html", departments=departments)


# ============================
# XÓA 1 NHÂN VIÊN
# ============================
@app.route("/employees/delete/<ma_nv>")
def delete_employee_web(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # --- Lấy tên nhân viên trước khi xóa ---
        cursor.execute("SELECT HoTen FROM NhanVien WHERE MaNV = ?", (ma_nv,))
        row = cursor.fetchone()
        old_name = row[0] if row else "(Không tìm thấy)"

        # --- Ghi log vào LichSuThayDoi ---
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, (
            "NhanVien",
            ma_nv,
            "Xóa",
            "HoTen",
            old_name,
            None,
            session.get("user_id")
        ))

        # --- Xóa dữ liệu liên quan theo thứ tự an toàn ---
        tables_to_delete = [
            "ChamCong",
            "LichLamViec",
            "KhuonMat",
            "Luong",
            "TaiKhoan"  # 🔥 thêm xóa tài khoản
        ]
        for table in tables_to_delete:
            cursor.execute(f"DELETE FROM {table} WHERE MaNV = ?", (ma_nv,))

        # Nếu nhân viên từng tính lương cho người khác
        cursor.execute("DELETE FROM Luong WHERE NguoiTinhLuong = ?", (ma_nv,))

        # --- Cuối cùng xóa nhân viên ---
        cursor.execute("DELETE FROM NhanVien WHERE MaNV = ?", (ma_nv,))

        conn.commit()
        flash(f"✅ Đã xóa nhân viên {ma_nv} và toàn bộ dữ liệu liên quan.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa nhân viên: {str(e)}", "danger")

    finally:
        conn.close()

    return redirect(url_for("employee_list"))



# ============================
# XÓA NHIỀU NHÂN VIÊN CÙNG LÚC
# ============================
@app.route("/employees/delete_selected", methods=["POST"])
def delete_selected_employees():
    selected_ids = request.form.getlist("selected_employees")

    if not selected_ids:
        flash("⚠️ Chưa chọn nhân viên nào để xóa!", "warning")
        return redirect(url_for("employee_list"))

    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        for ma_nv in selected_ids:
            # --- Lấy thông tin cũ để ghi log ---
            cursor.execute("SELECT HoTen FROM NhanVien WHERE MaNV = ?", (ma_nv,))
            row = cursor.fetchone()
            old_name = row[0] if row else "(Không tìm thấy)"

            # --- Ghi log vào bảng LichSuThayDoi ---
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "NhanVien",
                ma_nv,
                "Xóa",
                "HoTen",
                old_name,
                None,
                session.get("user_id")
            ))

            # --- Xóa dữ liệu liên quan ---
            tables_to_delete = [
                "ChamCong",
                "LichLamViec",
                "KhuonMat",
                "Luong",
                "TaiKhoan"
            ]
            for table in tables_to_delete:
                cursor.execute(f"DELETE FROM {table} WHERE MaNV = ?", (ma_nv,))

            cursor.execute("DELETE FROM Luong WHERE NguoiTinhLuong = ?", (ma_nv,))
            cursor.execute("DELETE FROM NhanVien WHERE MaNV = ?", (ma_nv,))

        conn.commit()
        flash(f"✅ Đã xóa {len(selected_ids)} nhân viên và toàn bộ dữ liệu liên quan.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa nhân viên: {str(e)}", "danger")

    finally:
        conn.close()

    return redirect(url_for("employee_list"))



# Route chỉnh sửa nhân viên
@app.route("/employees/edit/<ma_nv>", methods=["GET", "POST"], endpoint="edit_employee_web")
def edit_employee_web(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy thông tin nhân viên ---
    cursor.execute("""
        SELECT nv.MaNV, nv.HoTen, nv.Email, nv.SDT, nv.GioiTinh, nv.NgaySinh, nv.DiaChi, 
               nv.MaPB, nv.ChucVu, nv.TrangThai, pb.TenPB, km.DuongDanAnh
        FROM NhanVien nv
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat km ON nv.MaNV = km.MaNV
        WHERE nv.MaNV = ?
    """, (ma_nv,))
    row = cursor.fetchone()

    if not row:
        flash(f"Không tìm thấy nhân viên {ma_nv}", "error")
        conn.close()
        return redirect(url_for("employee_list"))

    columns = [col[0] for col in cursor.description]
    employee = dict(zip(columns, row))

    # ✅ Xử lý avatar (đọc từ thư mục photos/, không nằm trong static)
    avatar = employee.get("DuongDanAnh")

    if avatar and avatar.strip():
        avatar = avatar.replace("\\", "/")
        if not avatar.startswith("/"):
            avatar = f"/{avatar}"   # chuyển photos/NVTC7.jpg → /photos/NVTC7.jpg
        employee["AnhDaiDien"] = avatar
    else:
        employee["AnhDaiDien"] = "/photos/default.jpg"

    # --- Lấy danh sách phòng ban ---
    cursor.execute("SELECT MaPB, TenPB FROM PhongBan")
    departments = [dict(zip([c[0] for c in cursor.description], r)) for r in cursor.fetchall()]
    conn.close()

    # --- Nếu người dùng cập nhật ---
    if request.method == "POST":
        hoten = request.form.get("HoTen", "").strip()
        email = request.form.get("Email", "").strip()
        sdt = request.form.get("SDT", "").strip()
        gioitinh = int(request.form.get("GioiTinh", 1))
        ngaysinh = request.form.get("NgaySinh", "").strip() or None
        diachi = request.form.get("DiaChi", "").strip()
        ma_pb = request.form.get("MaPB", "").strip()
        chucvu = request.form.get("ChucVu", "").strip()
        trangthai = int(request.form.get("TrangThai", 1))
        file = request.files.get("avatar")

        conn = get_sql_connection()
        cursor = conn.cursor()

        # --- Lấy dữ liệu cũ để ghi log ---
        cursor.execute("SELECT * FROM NhanVien WHERE MaNV=?", (ma_nv,))
        old_data = cursor.fetchone()
        old_cols = [c[0] for c in cursor.description]
        old_emp = dict(zip(old_cols, old_data)) if old_data else {}

        # --- Cập nhật thông tin nhân viên ---
        cursor.execute("""
            UPDATE NhanVien
            SET HoTen=?, Email=?, SDT=?, GioiTinh=?, NgaySinh=?, DiaChi=?, MaPB=?, ChucVu=?, TrangThai=?
            WHERE MaNV=?
        """, (hoten, email, sdt, gioitinh, ngaysinh, diachi, ma_pb, chucvu, trangthai, ma_nv))
        conn.commit()

        # 🧾 Ghi log thay đổi
        fields = {
            "HoTen": hoten,
            "Email": email,
            "SDT": sdt,
            "GioiTinh": gioitinh,
            "NgaySinh": ngaysinh,
            "DiaChi": diachi,
            "MaPB": ma_pb,
            "ChucVu": chucvu,
            "TrangThai": trangthai
        }
        for field, new_val in fields.items():
            old_val = old_emp.get(field)
            if str(old_val) != str(new_val):
                cursor.execute("""
                    INSERT INTO LichSuThayDoi
                    (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, NguoiThucHien)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, ("NhanVien", ma_nv, "Sửa", field, str(old_val), str(new_val), session.get("user_id")))

        # --- Xử lý ảnh đại diện upload ---
        if file and file.filename != "":
            # Lưu file vào thư mục "photos" gốc
            os.makedirs("photos", exist_ok=True)
            filename = f"{ma_nv}.jpg"
            save_path = os.path.join("photos", filename)
            file.save(save_path)

            # Đường dẫn lưu trong DB (ví dụ: "photos/NVNS3.jpg")
            db_path = f"photos/{filename}"

            # Cập nhật bảng KhuonMat
            cursor.execute("SELECT COUNT(*) FROM KhuonMat WHERE MaNV=?", (ma_nv,))
            exists = cursor.fetchone()[0]
            if exists:
                cursor.execute("UPDATE KhuonMat SET DuongDanAnh=? WHERE MaNV=?", (db_path, ma_nv))
            else:
                cursor.execute("INSERT INTO KhuonMat (MaNV, DuongDanAnh, TrangThai) VALUES (?, ?, 1)", (ma_nv, db_path))

            # Ghi log thay đổi ảnh
            cursor.execute("""
                INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriMoi, NguoiThucHien)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("KhuonMat", ma_nv, "Cập nhật", "DuongDanAnh", db_path, session.get("user_id")))

            conn.commit()

        conn.commit()
        conn.close()

        flash("✅ Cập nhật thông tin nhân viên thành công!", "success")
        return redirect(url_for("employee_detail", ma_nv=ma_nv))

    # --- Trả về giao diện chỉnh sửa ---
    return render_template("edit_employee.html", employee=employee, departments=departments)



# QUẢN LÝ PHÒNG BAN

# --- Quản lý phòng ban (hiển thị + thêm + sửa + xóa) ---
@app.route("/departments")
def departments():
    conn = get_sql_connection()
    cursor = conn.cursor()
    keyword = request.args.get("q", "").strip()

    # --- Lấy danh sách phòng ban + số nhân viên + trạng thái + quản lý ---
    query = """
        SELECT pb.MaPB, pb.TenPB, pb.QuanLy, pb.TrangThai, COUNT(nv.MaNV) AS SoNhanVien
        FROM PhongBan pb
        LEFT JOIN NhanVien nv ON pb.MaPB = nv.MaPB
    """
    params = ()
    if keyword:
        query += " WHERE pb.TenPB LIKE ? OR pb.MaPB LIKE ?"
        params = (f"%{keyword}%", f"%{keyword}%")

    query += " GROUP BY pb.MaPB, pb.TenPB, pb.QuanLy, pb.TrangThai ORDER BY pb.MaPB"
    cursor.execute(query, params)
    rows = cursor.fetchall()

    # --- Chuẩn bị dữ liệu để render ---
    departments = []
    for row in rows:
        ma_pb, ten_pb, quan_ly, trang_thai, so_nv = row
        departments.append({
            "ma_pb": ma_pb,
            "ten_pb": ten_pb,
            "so_nv": so_nv,
            "manager": quan_ly if quan_ly else "Chưa có",
            "trang_thai": "Đang hoạt động" if trang_thai == 1 else "Ngừng hoạt động",
            "last_updated": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        })

    # --- Thống kê ---
    cursor.execute("SELECT COUNT(*) FROM PhongBan")
    total_departments = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM NhanVien")
    total_employees = cursor.fetchone()[0]

    # ✅ Dùng bit, không còn dùng chuỗi N'Đang hoạt động'
    cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE TrangThai = 1")
    active_departments = cursor.fetchone()[0]

    conn.close()

    # --- Render ra giao diện ---
    return render_template(
        "departments.html",
        departments=departments,
        keyword=keyword,
        total_departments=total_departments,
        total_employees=total_employees,
        active_departments=active_departments
    )


# --- Chi tiết phòng ban ---
@app.route("/departments/<ma_pb>")
def department_detail(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy thông tin phòng ban ---
    cursor.execute("""
        SELECT MaPB, TenPB, QuanLy, TrangThai, MoTa
        FROM PhongBan
        WHERE MaPB = ?
    """, (ma_pb,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        flash("Không tìm thấy phòng ban!", "error")
        return redirect(url_for("departments"))

    pb_info = {
        "ma_pb": row.MaPB,
        "ten_pb": row.TenPB,
        "quan_ly": row.QuanLy if row.QuanLy else "Chưa có",
        "trang_thai": "Đang hoạt động" if row.TrangThai == 1 else "Ngừng hoạt động",
        "mo_ta": row.MoTa if row.MoTa else "Không có mô tả"
    }

    # --- 🔹 Ghi lịch sử xem chi tiết ---
    try:
        username = session.get("username") or session.get("user_id") or "admin"
        cursor.execute("EXEC sys.sp_set_session_context @key=N'user', @value=?", (username,))
        cursor.execute("""
            INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, ThoiGian, NguoiThucHien)
            VALUES (N'PhongBan', ?, N'Xem chi tiết', GETDATE(), ?)
        """, (ma_pb, username))
        conn.commit()
    except Exception as e:
        print("⚠️ Lỗi ghi log xem chi tiết phòng ban:", e)

    # --- Lấy danh sách nhân viên trong phòng ---
    keyword = request.args.get("q", "").strip()
    order = request.args.get("sort", "ten")

    query = """
        SELECT MaNV, HoTen, ChucVu, NgayVaoLam
        FROM NhanVien
        WHERE MaPB = ?
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


#thêm phòng ban
@app.route("/departments/add", methods=["GET", "POST"])
def add_department():
    if request.method == "POST":
        ten_pb = request.form["ten_pb"].strip()
        mo_ta = request.form.get("mo_ta", "").strip()

        if not ten_pb:
            flash("Tên phòng ban không được để trống!", "error")
            return redirect(url_for("add_department"))

        # 🔹 Tạo mã viết tắt từ tên phòng ban
        # Ví dụ: "Công nghệ thông tin" -> "CNTT"
        words = ten_pb.split()
        ma_pb_base = "".join(w[0].upper() for w in words if w)
        ma_pb = ma_pb_base

        conn = get_sql_connection()
        cursor = conn.cursor()

        # 🔹 Nếu mã bị trùng, thêm số tăng dần phía sau: KD1, KD2, ...
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

        # 🔹 Thêm phòng ban vào database
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
def edit_department(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🔹 Lấy dữ liệu phòng ban cũ
    cursor.execute("SELECT MaPB, TenPB, MoTa, TrangThai FROM PhongBan WHERE MaPB = ?", (ma_pb,))
    department = cursor.fetchone()

    if not department:
        flash("❌ Không tìm thấy phòng ban!", "danger")
        conn.close()
        return redirect(url_for("departments"))

    old_ma_pb, old_ten_pb, old_mo_ta, old_trang_thai = department

    if request.method == "POST":
        ten_pb = request.form["ten_pb"].strip()
        mo_ta = request.form["mo_ta"].strip()
        trang_thai = 1 if request.form.get("trang_thai") == "on" else 0

        # 🔹 Hàm tạo mã viết tắt từ tên phòng ban
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
                flash("✅ Cập nhật mô tả phòng ban thành công!", "success")

            else:
                # 🔹 Kiểm tra trùng mã phòng ban
                cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE MaPB = ?", (new_ma_pb,))
                if cursor.fetchone()[0] > 0:
                    flash(f"❌ Mã phòng ban '{new_ma_pb}' đã tồn tại! Vui lòng chọn tên khác.", "danger")
                    conn.close()
                    return redirect(url_for("departments"))

                # 1️⃣ Tạo phòng ban mới
                cursor.execute("""
                    INSERT INTO PhongBan (MaPB, TenPB, MoTa, TrangThai)
                    VALUES (?, ?, ?, ?)
                """, (new_ma_pb, ten_pb, mo_ta, trang_thai))

                # 2️⃣ Lấy danh sách nhân viên thuộc phòng ban cũ
                cursor.execute("SELECT MaNV FROM NhanVien WHERE MaPB = ?", (old_ma_pb,))
                old_nv_list = [row[0] for row in cursor.fetchall()]

                # 3️⃣ Tắt toàn bộ ràng buộc FK liên quan đến MaNV
                cursor.execute("ALTER TABLE TaiKhoan NOCHECK CONSTRAINT FK_TaiKhoan_NhanVien")
                cursor.execute("ALTER TABLE KhuonMat NOCHECK CONSTRAINT FK__KhuonMat__MaNV__4222D4EF")
                cursor.execute("ALTER TABLE ChamCong NOCHECK CONSTRAINT FK__ChamCong__MaNV__4F7CD00D")
                cursor.execute("ALTER TABLE LichLamViec NOCHECK CONSTRAINT FK__LichLamVie__MaNV__4AB81AF0")

                # 4️⃣ Cập nhật mã nhân viên và đồng bộ sang các bảng liên quan
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

                # 5️⃣ Bật lại các ràng buộc FK
                cursor.execute("ALTER TABLE TaiKhoan WITH CHECK CHECK CONSTRAINT FK_TaiKhoan_NhanVien")
                cursor.execute("ALTER TABLE KhuonMat WITH CHECK CHECK CONSTRAINT FK__KhuonMat__MaNV__4222D4EF")
                cursor.execute("ALTER TABLE ChamCong WITH CHECK CHECK CONSTRAINT FK__ChamCong__MaNV__4F7CD00D")
                cursor.execute("ALTER TABLE LichLamViec WITH CHECK CHECK CONSTRAINT FK__LichLamVie__MaNV__4AB81AF0")

                # 6️⃣ Xóa phòng ban cũ
                cursor.execute("DELETE FROM PhongBan WHERE MaPB = ?", (old_ma_pb,))

                conn.commit()
                flash(f"✅ Đã đổi '{old_ten_pb}' → '{ten_pb}' (mã mới: {new_ma_pb}) và đồng bộ toàn bộ dữ liệu nhân viên, tài khoản, khuôn mặt, chấm công, lịch làm việc thành công!", "success")

        except Exception as e:
            conn.rollback()
            flash(f"❌ Lỗi khi cập nhật phòng ban: {e}", "danger")

        finally:
            conn.close()

        return redirect(url_for("departments"))

    conn.close()
    return render_template("edit_department.html", department=department)

# --- Xóa phòng ban ---
@app.route("/departments/delete/<ma_pb>", methods=["POST"])
def delete_department(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM PhongBan WHERE MaPB=?", (ma_pb,))
    conn.commit()
    conn.close()
    flash("Xóa phòng ban thành công!", "info")
    return redirect(url_for("departments"))

# ======================
# QUẢN LÝ CA LÀM
# ======================
from datetime import datetime
from datetime import datetime

from datetime import datetime, time

@app.route("/shifts")
def shifts():
    keyword = request.args.get("q", "").strip().lower()
    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🔹 Lấy danh sách ca làm việc
    cursor.execute("""
        SELECT MaCa, TenCa, GioBatDau, GioKetThuc, HeSo, MoTa
        FROM CaLamViec
    """)
    rows = cursor.fetchall()

    shifts = []
    from datetime import datetime

    for row in rows:
        ma_ca, ten_ca, gio_bd, gio_kt, he_so, mo_ta = row

        # Định dạng giờ
        def fmt(t):
            try:
                if isinstance(t, str):
                    return t[:5]
                return t.strftime("%H:%M")
            except Exception:
                return str(t)

        gio_bd_fmt = fmt(gio_bd)
        gio_kt_fmt = fmt(gio_kt)

        shifts.append({
            "MaCa": ma_ca,
            "TenCa": ten_ca,
            "GioBatDau": gio_bd_fmt,
            "GioKetThuc": gio_kt_fmt,
            "HeSoLuong": he_so,
            "MoTa": mo_ta,
            "TrangThai": "Đang hoạt động" if gio_bd_fmt <= datetime.now().strftime("%H:%M") <= gio_kt_fmt else "Ngoài giờ",
            "ThoiGian": f"{gio_bd_fmt} - {gio_kt_fmt}",
            "LastUpdated": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        })

    # 🔹 Lọc theo từ khóa tìm kiếm (nếu có)
    if keyword:
        shifts = [s for s in shifts if keyword in s["TenCa"].lower() or keyword in s["MaCa"].lower()]

    # 🔹 Tổng số ca đang hoạt động
    active_shifts = sum(1 for s in shifts if s["TrangThai"] == "Đang hoạt động")

    # 🔹 Tổng số nhân viên đã được phân ca (đếm thực tế trong LichLamViec)
    cursor.execute("""
        SELECT COUNT(DISTINCT MaNV)
        FROM LichLamViec
    """)
    total_assigned = cursor.fetchone()[0]

    conn.close()

    # 🔹 Render ra template
    return render_template(
        "shifts.html",
        shifts=shifts,
        active_shifts=active_shifts,
        total_employees=total_assigned,
        keyword=keyword
    )

#chi tiết ca
@app.route("/shifts/<ma_ca>")
def shift_detail(ma_ca):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy thông tin ca làm ---
    cursor.execute("""
        SELECT MaCa, TenCa, GioBatDau, GioKetThuc, HeSo, MoTa
        FROM CaLamViec
        WHERE MaCa = ?
    """, (ma_ca,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        flash("Không tìm thấy ca làm việc!", "error")
        return redirect(url_for("shifts"))

    ma_ca, ten_ca, gio_bd, gio_kt, he_so, mo_ta = row
    from datetime import datetime
    fmt_time = lambda t: t.strftime("%H:%M") if not isinstance(t, str) else t[:5]
    ca_info = {
        "ma_ca": ma_ca,
        "ten_ca": ten_ca,
        "gio_bd": fmt_time(gio_bd),
        "gio_kt": fmt_time(gio_kt),
        "he_so": he_so if he_so else "—",
        "mo_ta": mo_ta if mo_ta else "Không có mô tả",
        "trang_thai": "Đang hoạt động" if fmt_time(gio_bd) <= datetime.now().strftime("%H:%M") <= fmt_time(gio_kt) else "Ngoài giờ",
        "last_updated": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    }

    # --- 🔹 Ghi lịch sử xem chi tiết ---
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

    return render_template(
        "shift_detail.html",
        ca=ca_info,
        nhanviens=nhanviens,
        keyword=keyword,
        order=order
    )


#Thêm ca
@app.route("/add_shift", methods=["GET", "POST"])
def add_shift():
    if request.method == "POST":
        ma_ca = request.form["ma_ca"]
        gio_bd = request.form["gio_bat_dau"]
        gio_kt = request.form["gio_ket_thuc"]
        manage_shift.add_shift(ma_ca, gio_bd, gio_kt)
        flash("Thêm ca làm thành công!", "success")
        return redirect(url_for("shifts"))
    return render_template("add_shift.html")
#Chỉnh sửa ca
@app.route("/edit_shift/<ma_ca>", methods=["GET", "POST"])
def edit_shift(ma_ca):
    if request.method == "POST":
        gio_bd = request.form["gio_bat_dau"]
        gio_kt = request.form["gio_ket_thuc"]
        manage_shift.update_shift(ma_ca, gio_bd, gio_kt)
        flash("Cập nhật ca làm thành công!", "success")
        return redirect(url_for("shifts"))
    return render_template("edit_shift.html", ma_ca=ma_ca)
#Xóa ca
@app.route("/delete_shift/<ma_ca>")
def delete_shift(ma_ca):
    manage_shift.delete_shift(ma_ca)
    flash("Xóa ca làm thành công!", "danger")
    return redirect(url_for("shifts"))

def mark_absent_employees():
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE llv
        SET llv.TrangThai = 2   -- 2 = Vắng
        FROM LichLamViec AS llv
        INNER JOIN CaLamViec AS clv ON llv.MaCa = clv.MaCa
        WHERE llv.TrangThai = 0
          AND (
                -- Ca ở ngày trước hôm nay: vắng nếu chưa chấm
                llv.NgayLam < CAST(GETDATE() AS DATE)
                -- Ca hôm nay: chỉ vắng khi đã qua giờ kết thúc
                OR (llv.NgayLam = CAST(GETDATE() AS DATE)
                    AND CONVERT(TIME, GETDATE()) > clv.GioKetThuc)
              )
          AND NOT EXISTS (
                SELECT 1
                FROM ChamCong AS cc
                WHERE cc.MaNV = llv.MaNV
                  AND cc.NgayChamCong = llv.NgayLam
                  AND (
                        (cc.GioVao BETWEEN clv.GioBatDau AND clv.GioKetThuc)
                     OR (cc.GioRa  BETWEEN clv.GioBatDau AND clv.GioKetThuc)
                     OR (cc.GioVao <= clv.GioBatDau AND (cc.GioRa IS NULL OR cc.GioRa >= clv.GioKetThuc))
                  )
          );
    """)
    conn.commit()
    conn.close()


# =========================
# 🔹 Trang danh sách nhân viên đã phân ca
# =========================
@app.route("/assigned_employees")
def assigned_employees():
    conn = get_sql_connection()
    cursor = conn.cursor()
    now = datetime.now()
    today = now.date()

    # --- Lấy toàn bộ phân ca ---
    cursor.execute("""
        SELECT llv.MaLLV, llv.MaNV, llv.MaCa, llv.NgayLam, llv.TrangThai,
               clv.GioBatDau, clv.GioKetThuc
        FROM LichLamViec llv
        LEFT JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
    """)
    lichlamviec = cursor.fetchall()

    # ✅ Hàm chuyển đổi an toàn
    def to_date(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return datetime.strptime(value.split(" ")[0], "%Y-%m-%d").date()
            except:
                return None
        return None

    def to_time(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value.time()
        if isinstance(value, str):
            try:
                # Nếu chỉ có "08:00:00"
                return datetime.strptime(value.strip(), "%H:%M:%S").time()
            except:
                return None
        return None

    # --- Cập nhật trạng thái ---
    for ma_llv, ma_nv, ma_ca, ngay_lam, trang_thai, gio_bat_dau, gio_ket_thuc in lichlamviec:
        ngay_lam = to_date(ngay_lam)
        gio_bat_dau = to_time(gio_bat_dau)
        gio_ket_thuc = to_time(gio_ket_thuc)

        if not ngay_lam:
            continue

        new_status = trang_thai

        # ✅ Cập nhật trạng thái theo thời gian thực
        if trang_thai == 0:  # Chưa chấm
            if ngay_lam < today:
                new_status = 2  # Quá ngày => vắng
            elif ngay_lam == today:
                if gio_ket_thuc and now.time() > gio_ket_thuc:
                    new_status = 2
            # Ngày tương lai: giữ nguyên 0

            if new_status != trang_thai:
                cursor.execute(
                    "UPDATE LichLamViec SET TrangThai = ? WHERE MaLLV = ?",
                    (new_status, ma_llv)
                )

    conn.commit()

    # --- Lấy danh sách hiển thị ---
    cursor.execute("""
        SELECT llv.MaLLV, nv.MaNV, nv.HoTen, pb.TenPB,
               clv.TenCa, clv.GioBatDau, clv.GioKetThuc,
               llv.NgayLam, llv.TrangThai,
               CASE llv.TrangThai
                    WHEN 0 THEN N'Chưa chấm'
                    WHEN 1 THEN N'Đã chấm công'
                    WHEN 2 THEN N'Vắng'
               END AS TrangThaiText
        FROM LichLamViec llv
        LEFT JOIN NhanVien nv ON llv.MaNV = nv.MaNV
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
        ORDER BY llv.NgayLam DESC, nv.HoTen
    """)
    columns = [col[0] for col in cursor.description]
    records = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()

    # --- Chuẩn hóa kiểu dữ liệu để render ---
    for r in records:
        r["NgayLam"] = to_date(r.get("NgayLam"))
        r["GioBatDau"] = to_time(r.get("GioBatDau"))
        r["GioKetThuc"] = to_time(r.get("GioKetThuc"))

    # --- Đếm thống kê ---
    present_count = sum(1 for r in records if r["TrangThai"] == 1)
    absent_count = sum(1 for r in records if r["TrangThai"] == 2)
    pending_count = sum(1 for r in records if r["TrangThai"] == 0)

    return render_template(
        "assigned_employees.html",
        records=records,
        present_count=present_count,
        absent_count=absent_count,
        pending_count=pending_count
    )

# 🔹 Trang phân ca mới
# ======================
@app.route("/assign_shift", methods=["GET", "POST"])
def assign_shift():
    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🟢 Khi người dùng bấm Lưu
    if request.method == "POST":
        MaNV = request.form.get("MaNV")
        MaCa = request.form.get("MaCa")
        NgayLam = request.form.get("NgayLam")

        if not MaNV or not MaCa or not NgayLam:
            flash("❌ Vui lòng điền đầy đủ thông tin!", "danger")
            return redirect(url_for("assign_shift"))

        # 🟡 Kiểm tra trùng lịch
        cursor.execute("""
            SELECT COUNT(*) FROM LichLamViec
            WHERE MaNV=? AND MaCa=? AND NgayLam=?
        """, (MaNV, MaCa, NgayLam))
        exists = cursor.fetchone()[0]

        if exists:
            flash("⚠️ Nhân viên này đã được phân ca trong ngày đó!", "warning")
        else:
            cursor.execute("""
                INSERT INTO LichLamViec (MaNV, MaCa, NgayLam, TrangThai)
                VALUES (?, ?, ?, 0)
            """, (MaNV, MaCa, NgayLam))
            conn.commit()
            flash("✅ Đã phân ca làm việc thành công!", "success")

        conn.close()
        return redirect(url_for("assigned_employees"))

    # 🟢 Khi mở form (GET)
    cursor.execute("SELECT MaNV, HoTen FROM NhanVien ORDER BY HoTen")
    employees = cursor.fetchall()

    cursor.execute("SELECT MaCa, TenCa FROM CaLamViec ORDER BY MaCa")
    shifts = cursor.fetchall()

    conn.close()
    return render_template("assign_shift.html", employees=employees, shifts=shifts)

# ======================
# ✏️ Sửa phân ca
@app.route("/edit_shift_assignment/<int:id>", methods=["GET", "POST"])
def edit_shift_assignment(id):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🔹 Lấy dữ liệu hiện tại
    cursor.execute("""
        SELECT LLV.MaLLV, LLV.MaNV, LLV.MaCa, LLV.NgayLam, NV.HoTen, CLV.TenCa
        FROM LichLamViec LLV
        LEFT JOIN NhanVien NV ON NV.MaNV = LLV.MaNV
        LEFT JOIN CaLamViec CLV ON CLV.MaCa = LLV.MaCa
        WHERE LLV.MaLLV = ?
    """, (id,))
    record = cursor.fetchone()

    # ⚙️ Nếu có giá trị ngày, ép kiểu thành datetime để HTML dùng .strftime()
    if record and isinstance(record.NgayLam, str):
        try:
            record.NgayLam = datetime.strptime(record.NgayLam, "%Y-%m-%d")
        except ValueError:
            record.NgayLam = None

    # 🔹 Lấy danh sách nhân viên & ca làm
    cursor.execute("SELECT MaNV, HoTen FROM NhanVien")
    employees = cursor.fetchall()

    cursor.execute("SELECT MaCa, TenCa FROM CaLamViec")
    shifts = cursor.fetchall()

    # 🔹 Khi người dùng bấm “Lưu”
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
        flash("✏️ Đã cập nhật thông tin phân ca!", "success")
        return redirect(url_for("assigned_employees"))

    conn.close()
    return render_template("edit_shift_assignment.html", record=record, employees=employees, shifts=shifts)
# ======================
# 🗑️ Xóa phân ca
# ======================
# ✅ Xóa từng phân ca
@app.route("/delete_shift_assignment/<int:id>", methods=["GET", "POST"])
def delete_shift_assignment(id):
    manage_assignment.delete_assignment(id)
    flash("Đã xóa phân ca thành công!", "danger")
    return redirect(url_for("assigned_employees"))


# ✅ Xóa nhiều phân ca (bulk delete)
@app.route("/delete_shift_assignment", methods=["POST"])
def delete_multiple_shift_assignments():
    selected_ids = request.form.getlist("selected_assignments")
    if not selected_ids:
        flash("Chưa chọn phân ca nào để xóa!", "warning")
    else:
        for record_id in selected_ids:
            manage_assignment.delete_assignment(record_id)
        flash(f"Đã xóa {len(selected_ids)} phân ca đã chọn!", "danger")
    return redirect(url_for("assigned_employees"))


# QUẢN LÝ TÀI KHOẢN
# ======================
@app.route("/accounts")
def accounts():
    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🔹 Tổng số tài khoản
    cursor.execute("SELECT COUNT(*) FROM TaiKhoan")
    total_accounts = cursor.fetchone()[0]

    # 🔹 Tài khoản đang hoạt động
    cursor.execute("SELECT COUNT(*) FROM TaiKhoan WHERE TrangThai = 1")
    active_accounts = cursor.fetchone()[0]

    # 🔹 Đếm số Quản trị viên (hỗ trợ nhiều cách ghi)
    cursor.execute("""
        SELECT COUNT(*) FROM TaiKhoan
        WHERE LOWER(VaiTro) IN (N'admin', N'quản trị viên', N'administrator')
    """)
    admin_accounts = cursor.fetchone()[0]

    # 🔹 Đếm số Nhân viên (hỗ trợ nhiều cách ghi)
    cursor.execute("""
        SELECT COUNT(*) FROM TaiKhoan
        WHERE LOWER(VaiTro) IN (N'user', N'nhanvien', N'nhân viên', N'người dùng')
    """)
    user_accounts = cursor.fetchone()[0]

    # 🔹 Lấy danh sách tài khoản (hiển thị đầy đủ, vai trò tiếng Việt)
    cursor.execute("""
        SELECT 
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
            CONVERT(VARCHAR(10), t.NgayTao, 103) AS NgayTao
        FROM TaiKhoan AS t
        LEFT JOIN NhanVien AS n ON t.MaNV = n.MaNV
        ORDER BY t.NgayTao DESC
    """)
    accounts = cursor.fetchall()

    conn.close()

    # 🔹 Trả dữ liệu ra giao diện
    return render_template(
        "accounts.html",
        accounts=accounts,
        total_accounts=total_accounts,
        active_accounts=active_accounts,
        admin_accounts=admin_accounts,
        user_accounts=user_accounts
    )

# ======================
# KÍCH HOẠT TÀI KHOẢN
# ======================
@app.route("/accounts/activate/<username>")
def activate_account(username):
    conn = get_sql_connection()
    cursor = conn.cursor()

    cursor.execute("UPDATE TaiKhoan SET TrangThai = 1 WHERE TenDangNhap = ?", (username,))
    conn.commit()
    conn.close()

    flash(f"✅ Đã kích hoạt tài khoản: {username}", "success")
    return redirect(url_for("accounts"))


# ======================
# VÔ HIỆU HÓA TÀI KHOẢN
# ======================
@app.route("/accounts/deactivate/<username>")
def deactivate_account(username):
    conn = get_sql_connection()
    cursor = conn.cursor()

    cursor.execute("UPDATE TaiKhoan SET TrangThai = 0 WHERE TenDangNhap = ?", (username,))
    conn.commit()
    conn.close()

    flash(f"🚫 Đã vô hiệu hóa tài khoản: {username}", "warning")
    return redirect(url_for("accounts"))
# ======================
# CHUYỂN TRẠNG THÁI (AJAX)
# ======================
@app.route("/accounts/toggle_status/<username>", methods=["POST"])
def toggle_account_status(username):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # Lấy trạng thái hiện tại
    cursor.execute("SELECT TrangThai FROM TaiKhoan WHERE TenDangNhap = ?", (username,))
    result = cursor.fetchone()

    if not result:
        conn.close()
        return jsonify({"success": False, "message": "Không tìm thấy tài khoản."})

    current_status = result[0]
    new_status = 0 if current_status == 1 else 1  # đảo trạng thái

    # Cập nhật trạng thái
    cursor.execute("UPDATE TaiKhoan SET TrangThai = ? WHERE TenDangNhap = ?", (new_status, username))
    conn.commit()
    conn.close()

    return jsonify({
        "success": True,
        "username": username,
        "new_status": new_status,
        "status_text": "Đang hoạt động" if new_status == 1 else "Ngừng hoạt động"
    })

@app.route("/add_account", methods=["GET", "POST"])
def add_account_route():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()

        # Kiểm tra dữ liệu nhập vào
        if not username or not password or not role:
            flash("❌ Vui lòng nhập đầy đủ thông tin!", "danger")
            return redirect(url_for("add_account_route"))

        # Hash mật khẩu trước khi lưu
        hashed_password = hashlib.sha256(password.encode("utf-8")).hexdigest()

        # Gọi hàm thêm tài khoản
        add_account(username, hashed_password, role)

        flash("✅ Thêm tài khoản thành công!", "success")
        return redirect(url_for("accounts"))

    return render_template("add_account.html")

@app.route("/edit_account/<username>", methods=["GET", "POST"])
def edit_account(username):
    if request.method == "POST":
        password = request.form.get("password")  # có thể để trống
        role = request.form["role"]
        manage_account.update_account(username, password=password, role=role)
        flash("Cập nhật tài khoản thành công!", "success")
        return redirect(url_for("accounts"))
    return render_template("edit_account.html", username=username)

@app.route("/delete_account/<username>")
def delete_account(username):
    manage_account.delete_account(username)
    flash("Xóa tài khoản thành công!", "danger")
    return redirect(url_for("accounts"))


# ======================
# BÁO CÁO THỐNG KÊ
# ======================
@app.route('/reports')
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

    # 👉 Đếm tất cả phòng ban, không phân biệt trạng thái
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
def attendance_report():
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lọc theo tháng / năm ---
    month = request.args.get("month")
    year = request.args.get("year")

    filter_query, params = "", []
    if month and year:
        filter_query = "WHERE MONTH(CC.NgayChamCong)=? AND YEAR(CC.NgayChamCong)=?"
        params = [month, year]
    elif year:
        filter_query = "WHERE YEAR(CC.NgayChamCong)=?"
        params = [year]

    # --- Lấy dữ liệu chấm công ---
    cursor.execute(f"""
        SELECT 
            CC.MaChamCong, NV.MaNV, NV.HoTen, PB.TenPB AS PhongBan,
            FORMAT(CC.NgayChamCong, 'yyyy-MM-dd') AS NgayChamCong,
            FORMAT(CC.GioVao, 'HH:mm') AS GioVao,
            FORMAT(CC.GioRa, 'HH:mm') AS GioRa,
            
            -- Xác định ca làm theo giờ vào
            CASE 
                WHEN DATEPART(HOUR, CC.GioVao) BETWEEN 5 AND 11 THEN N'Ca sáng'
                WHEN DATEPART(HOUR, CC.GioVao) BETWEEN 11 AND 17 THEN N'Ca chiều'
                WHEN DATEPART(HOUR, CC.GioVao) BETWEEN 17 AND 23 THEN N'Ca tối'
                ELSE N'Không xác định'
            END AS CaLam,
            
            -- Tính số giờ làm (nếu có giờ ra)
            CASE 
                WHEN CC.GioRa IS NOT NULL THEN DATEDIFF(MINUTE, CC.GioVao, CC.GioRa) / 60.0
                ELSE 0
            END AS SoGioLam,
            
            -- Trạng thái chữ
            CASE 
                WHEN CC.TrangThai = 1 THEN N'Đúng giờ'
                WHEN CC.TrangThai = 2 THEN N'Đi muộn'
                WHEN CC.TrangThai = 3 THEN N'Vắng'
                ELSE N'Chưa xác định'
            END AS TrangThaiText
        FROM ChamCong CC
        LEFT JOIN NhanVien NV ON CC.MaNV = NV.MaNV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
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

    # --- Trả về giao diện ---
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
            flash("✅ Đã thêm bản ghi chấm công mới!", "success")
            return redirect(url_for("attendance_report"))
        except Exception as e:
            flash(f"❌ Lỗi khi thêm chấm công: {e}", "error")
        finally:
            conn.close()

    # Danh sách nhân viên đang hoạt động
    cursor.execute("SELECT MaNV, HoTen FROM NhanVien WHERE TrangThai=1")
    employees = cursor.fetchall()
    conn.close()
    return render_template("attendance_add.html", employees=employees)


# SỬA CHẤM CÔNG

@app.route("/attendance/edit/<int:id>", methods=["GET", "POST"])
def edit_attendance(id):
    conn = get_sql_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        try:
            GioVao = request.form["GioVao"]
            GioRa = request.form.get("GioRa") or None
            TrangThai = int(request.form["TrangThai"])

            # ⚠️ Quan trọng: Lấy đúng tên field là MaCa (mã ca), KHÔNG phải CaLam (nhãn)
            MaCa = request.form.get("MaCa") or None

            # Nếu form không chọn mã ca → giữ nguyên mã ca cũ (tránh set rỗng gây lỗi FK)
            if MaCa is None or MaCa.strip() == "":
                cursor.execute("SELECT MaCa FROM ChamCong WHERE MaChamCong = ?", (id,))
                row_ma = cursor.fetchone()
                MaCa = row_ma[0] if row_ma else None

            # ✅ Validate MaCa có tồn tại trong CaLamViec
            if MaCa:
                cursor.execute("SELECT 1 FROM CaLamViec WHERE MaCa = ?", (MaCa,))
                if cursor.fetchone() is None:
                    flash("❌ Mã ca không hợp lệ. Vui lòng chọn lại.", "error")
                    conn.close()
                    return redirect(url_for("attendance_edit", id=id))

            # Cập nhật dữ liệu
            cursor.execute("""
                UPDATE ChamCong
                SET GioVao = ?, GioRa = ?, TrangThai = ?, MaCa = ?
                WHERE MaChamCong = ?
            """, (GioVao, GioRa, TrangThai, MaCa, id))

            conn.commit()
            flash("✏️ Đã cập nhật bản ghi chấm công!", "info")
            conn.close()
            return redirect(url_for("attendance_report"))

        except Exception as e:
            conn.rollback()
            flash(f"❌ Lỗi khi cập nhật: {e}", "error")
            conn.close()
            return redirect(url_for("attendance_report"))

    # ---------- GET: lấy bản ghi + danh sách ca ----------
    cursor.execute("""
        SELECT 
            CC.MaChamCong, CC.MaNV, NV.HoTen, PB.TenPB,
            CC.NgayChamCong, CC.GioVao, CC.GioRa, CC.TrangThai,
            CC.MaCa,                                 -- ⚠️ LẤY ĐÚNG MÃ CA HIỆN TẠI
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
        flash("❌ Không tìm thấy bản ghi chấm công.", "error")
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

@app.route("/attendance/delete/<int:id>", methods=["POST"])
def delete_attendance(id):
    conn = get_sql_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM ChamCong WHERE MaChamCong=?", (id,))
        conn.commit()
        flash("🗑️ Đã xóa bản ghi chấm công!", "danger")
    except Exception as e:
        flash(f"❌ Lỗi khi xóa: {e}", "error")
    finally:
        conn.close()
    return redirect(url_for("attendance_report"))

salary_bp = Blueprint("salary", __name__)

#lương
# ==============================
# 🧮 Hàm tính lương 1 nhân viên (theo chức vụ Trưởng phòng)
# ==============================
def tinh_luong_nv(cursor, ma_nv, thangnam, nguoi_tinh):
    current_month = thangnam.month
    current_year = thangnam.year

    # 🔹 Kiểm tra nhân viên có phải Trưởng phòng không
    cursor.execute("""
        SELECT 1 
        FROM NhanVien NV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        WHERE NV.MaNV = ? 
          AND LOWER(NV.ChucVu) LIKE N'%trưởng phòng%'
    """, (ma_nv,))
    is_manager = cursor.fetchone() is not None  # True nếu là Trưởng phòng

    # 🔹 Lấy tổng số giờ làm trong tháng
    cursor.execute("""
        SELECT 
            SUM(DATEDIFF(MINUTE, GioVao, GioRa))/60.0 AS SoGioLam
        FROM ChamCong
        WHERE MaNV = ? AND MONTH(NgayChamCong) = ? AND YEAR(NgayChamCong) = ?
    """, (ma_nv, current_month, current_year))
    sogiolam = cursor.fetchone()[0] or 0

    # 🔹 Lấy tổng giờ làm theo từng ca
    cursor.execute("""
        SELECT MaCa, SUM(DATEDIFF(MINUTE, GioVao, GioRa))/60.0 AS GioCa
        FROM ChamCong
        WHERE MaNV = ? AND MONTH(NgayChamCong) = ? AND YEAR(NgayChamCong) = ?
        GROUP BY MaCa
    """, (ma_nv, current_month, current_year))
    ca_records = cursor.fetchall()

    tong_tien = 0
    for ma_ca, gio_ca in ca_records:
        ca = (ma_ca or "").lower()
        gio = float(gio_ca or 0)

        # ⚙️ Quy tắc lương theo ca
        if ca in ["ca1", "ca 1"]:
            he_so, muc_gio, muc_ca = 1.0, 100000, 500000
        elif ca in ["ca2", "ca 2"]:
            he_so, muc_gio, muc_ca = 1.0, 100000, 500000
        elif ca in ["ca3", "ca 3"]:
            he_so, muc_gio, muc_ca = 1.6, 100000, 800000
        else:
            he_so, muc_gio, muc_ca = 1.0, 100000, 0

        # 🔹 Nếu là Trưởng phòng → nhân hệ số bổ sung
        if is_manager:
            if ca in ["ca3", "ca 3"]:
                he_so *= 1.8  # ca đêm
            else:
                he_so *= 1.2  # ca ngày

        # 🔹 Nếu làm >= 4 tiếng → tính trọn ca, ngược lại tính theo giờ
        if gio >= 4:
            tien_ca = muc_ca * he_so
        else:
            tien_ca = gio * muc_gio * he_so

        tong_tien += tien_ca

    # 🔹 Nếu không có bản ghi ca nào → tính theo giờ
    if not ca_records:
        he_so_cv = 1.2 if is_manager else 1.0
        tong_tien = sogiolam * 100000 * he_so_cv

    # 🔹 Xóa bản ghi lương cũ trong tháng nếu có
    cursor.execute("""
        DELETE FROM Luong 
        WHERE MaNV = ? AND MONTH(ThangNam) = ? AND YEAR(ThangNam) = ?
    """, (ma_nv, current_month, current_year))

    # 🔹 Thêm bản ghi mới
    cursor.execute("""
        INSERT INTO Luong (MaNV, ThangNam, SoGioLam, TongTien, TrangThai, NguoiTinhLuong, NgayTinhLuong)
        VALUES (?, ?, ?, ?, 1, ?, GETDATE())
    """, (ma_nv, thangnam, sogiolam, tong_tien, nguoi_tinh))

# ==============================
# 📊 Trang hiển thị bảng lương
# ==============================
@app.route("/salary")
def salary_view():
    conn = get_sql_connection()
    cursor = conn.cursor()

    current_year = datetime.now().year
    current_month = datetime.now().month
    thangnam = datetime(current_year, current_month, 1)

    # Tổng nhân viên
    cursor.execute("SELECT COUNT(*) FROM NhanVien")
    total_employees = cursor.fetchone()[0] or 0

# 🔹 Đã tính lương (đếm nhân viên duy nhất có lương tháng này)
    cursor.execute("""
        SELECT COUNT(DISTINCT MaNV)
        FROM Luong
        WHERE MONTH(ThangNam) = ? AND YEAR(ThangNam) = ?
    """, (current_month, current_year))
    total_salaried = cursor.fetchone()[0] or 0

    # 🔹 Nhân viên chưa tính lương
    total_unsalaried = max(total_employees - total_salaried, 0)


    # Tổng quỹ lương
    cursor.execute("""
        SELECT SUM(TongTien) 
        FROM Luong 
        WHERE FORMAT(ThangNam, 'yyyy-MM') = FORMAT(?, 'yyyy-MM')
    """, (thangnam,))
    total_salary = cursor.fetchone()[0] or 0

    # Danh sách chi tiết nhân viên
    cursor.execute("""
        SELECT 
            NV.MaNV,
            NV.HoTen,
            PB.TenPB AS PhongBan,
            ISNULL(L.SoGioLam, 0) AS SoGioLam,
            ISNULL(L.TongTien, 0) AS TongTien,
            ISNULL(L.TrangThai, 0) AS TrangThai
        FROM NhanVien NV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        LEFT JOIN Luong L 
            ON NV.MaNV = L.MaNV 
            AND FORMAT(L.ThangNam, 'yyyy-MM') = FORMAT(?, 'yyyy-MM')
        ORDER BY NV.MaNV
    """, (thangnam,))
    cols = [c[0] for c in cursor.description]
    salaries = [dict(zip(cols, row)) for row in cursor.fetchall()]

    cursor.close()
    conn.close()

    return render_template("salary.html",
        total_employees=total_employees,
        total_salaried=total_salaried,
        total_unsalaried=total_unsalaried,
        total_salary=total_salary,
        salaries=salaries,
        current_month=current_month,
        current_year=current_year
    )


# ==============================
# 🧾 Tính lương cho toàn bộ nhân viên
# ==============================
@app.route("/calculate_salary")
def calculate_all_salary():
    conn = get_sql_connection()
    cursor = conn.cursor()
    current_year = datetime.now().year
    current_month = datetime.now().month
    thangnam = datetime(current_year, current_month, 1)
    nguoi_tinh = session.get("username", "Admin")

    try:
        cursor.execute("SELECT MaNV FROM NhanVien")
        for (ma_nv,) in cursor.fetchall():
            tinh_luong_nv(cursor, ma_nv, thangnam, nguoi_tinh)
        conn.commit()
        return jsonify({"success": True, "message": "✅ Đã tính lương cho tất cả nhân viên!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": f"❌ Lỗi khi tính: {e}"})
    finally:
        cursor.close()
        conn.close()


# ==============================
# 🧮 Tính lương cho 1 nhân viên
# ==============================
@app.route("/calculate_salary/<ma_nv>")
def calculate_one_salary(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()
    current_year = datetime.now().year
    current_month = datetime.now().month
    thangnam = datetime(current_year, current_month, 1)
    nguoi_tinh = session.get("username", "Admin")

    try:
        tinh_luong_nv(cursor, ma_nv, thangnam, nguoi_tinh)
        conn.commit()
        return jsonify({"success": True, "message": f"✅ Đã tính lương cho {ma_nv}!"})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": f"❌ Lỗi khi tính: {e}"})
    finally:
        cursor.close()
        conn.close()
# ==============================
# 📋 Trang chi tiết lương nhân viên (phân loại chức vụ)
# ==============================
@app.route("/salary/<ma_nv>")
def salary_detail(ma_nv):
    from datetime import datetime
    conn = get_sql_connection()
    cursor = conn.cursor()

    current_year = datetime.now().year
    current_month = datetime.now().month

    # 🔹 Lấy thông tin nhân viên + chức vụ + phòng ban
    cursor.execute("""
        SELECT NV.MaNV, NV.HoTen, NV.ChucVu, PB.TenPB
        FROM NhanVien NV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        WHERE NV.MaNV = ?
    """, (ma_nv,))
    emp = cursor.fetchone()
    if not emp:
        conn.close()
        return f"<h3>❌ Không tìm thấy nhân viên {ma_nv}</h3>"

    # 🔹 Ghi lịch sử xem chi tiết lương
    try:
        username = session.get("username") or session.get("user_id") or "admin"
        cursor.execute("EXEC sys.sp_set_session_context @key=N'user', @value=?", (username,))
        cursor.execute("""
            INSERT INTO LichSuThayDoi (TenBang, MaBanGhi, HanhDong, ThoiGian, NguoiThucHien)
            VALUES (N'Luong', ?, N'Xem chi tiết', GETDATE(), ?)
        """, (ma_nv, username))
        conn.commit()
    except Exception as e:
        print("⚠️ Lỗi ghi log xem chi tiết lương:", e)

    chucvu = (emp[2] or "").lower()

    # ✅ Xác định loại chức vụ & hệ số bổ sung
    if "trưởng phòng" in chucvu:
        role_label = "Trưởng phòng"
        role_icon = "fa-star text-warning"
        role_coef_day = 1.2
        role_coef_night = 1.8
    elif "phó phòng" in chucvu:
        role_label = "Phó phòng"
        role_icon = "fa-crown text-info"
        role_coef_day = 1.1
        role_coef_night = 1.5
    elif "thực tập" in chucvu or "intern" in chucvu:
        role_label = "Thực tập sinh"
        role_icon = "fa-user-graduate text-secondary"
        role_coef_day = 0.8
        role_coef_night = 1.0
    else:
        role_label = "Nhân viên"
        role_icon = "fa-user text-primary"
        role_coef_day = 1.0
        role_coef_night = 1.6

    # 🔹 Lấy chi tiết chấm công trong tháng hiện tại
    cursor.execute("""
        SELECT 
            CC.NgayChamCong,
            CC.MaCa,
            CC.GioVao,
            CC.GioRa,
            CAST(DATEDIFF(MINUTE, GioVao, GioRa)/60.0 AS DECIMAL(10,2)) AS SoGio
        FROM ChamCong CC
        WHERE CC.MaNV = ? AND MONTH(NgayChamCong) = ? AND YEAR(NgayChamCong) = ?
        ORDER BY NgayChamCong
    """, (ma_nv, current_month, current_year))

    cols = [c[0] for c in cursor.description]
    records = [dict(zip(cols, row)) for row in cursor.fetchall()]

    tong_gio = 0
    tong_tien = 0

    for r in records:
        ca = (r["MaCa"] or "").lower()
        gio = float(r["SoGio"] or 0)

        # ⚙️ Mức cơ bản theo ca
        if ca in ["ca1", "ca 1"]:
            he_so, muc_gio, muc_ca = role_coef_day, 100000, 500000
        elif ca in ["ca2", "ca 2"]:
            he_so, muc_gio, muc_ca = role_coef_day, 100000, 500000
        elif ca in ["ca3", "ca 3"]:
            he_so, muc_gio, muc_ca = role_coef_night, 100000, 800000
        else:
            he_so, muc_gio, muc_ca = role_coef_day, 100000, 0

        # 🔹 Nếu làm >= 4 tiếng → tính trọn ca
        if gio >= 4:
            tien_ca = muc_ca * he_so
        else:
            tien_ca = gio * muc_gio * he_so

        r["HeSo"] = he_so
        r["TienCa"] = tien_ca
        tong_gio += gio
        tong_tien += tien_ca

    conn.close()

    return render_template(
        "salary_detail.html",
        emp=emp,
        records=records,
        tong_gio=tong_gio,
        tong_tien=tong_tien,
        role_label=role_label,
        role_icon=role_icon,
        current_month=current_month,
        current_year=current_year
    )

# ==============================
# 🕓 Lịch sử thay đổi
# ==============================
@app.route("/history")
def history():
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            ls.*, 
            COALESCE(tk.TenDangNhap, ls.NguoiThucHien) AS TenDangNhap
        FROM LichSuThayDoi ls
        LEFT JOIN TaiKhoan tk 
            ON TRY_CAST(ls.NguoiThucHien AS INT) = tk.MaTK
        ORDER BY ls.ThoiGian DESC
    """)

    rows = cursor.fetchall()
    conn.close()
    return render_template("history.html", histories=rows)


@app.route("/settings", endpoint='settings')
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

# ======================
# Run app
# ======================
if __name__ == "__main__":
    app.run(debug=True)


