from flask import Flask, render_template, request, redirect, url_for, flash, Response, session, jsonify, send_from_directory, send_file
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from datetime import datetime
import pyodbc, hashlib, os, base64, io, random, smtplib, traceback, threading
from collections import Counter
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from PIL import ImageFont, ImageDraw, Image
from docx import Document
from openpyxl import Workbook
import datetime as dt
import time as tm
import socket
import cv2
from routes.attendance_system import load_known_faces, generate_frames, update_current_employee
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.INFO) 

import atexit
from core.face_utils import generate_frames

# --- Import core ---
from core.db_utils import (
    get_sql_connection, get_connection, get_phongbans, find_employees_by_name_or_manv
)
from core.decorators import require_role
from core.salary_utils import tinh_luong_nv, get_tham_so_luong
from core.face_utils import encode_and_save
from core.email_utils import send_email_notification
from core.config_mail import mail  


# 🔧 Tạo Flask App và cấu hình

app = Flask(__name__)
app.secret_key = "faceid_secret_2025"

# --- Cấu hình Flask-Mail ---
app.config.update(
    MAIL_SERVER='smtp.gmail.com',
    MAIL_PORT=587,
    MAIL_USE_TLS=True,
    MAIL_USERNAME='tranminhhop09@gmail.com',
    MAIL_PASSWORD='jqow ssav eltz eugk',
    MAIL_DEFAULT_SENDER=('FaceID System', 'tranminhhop09@gmail.com'),
    MAX_CONTENT_LENGTH=16 * 1024 * 1024
)
app.config["MAIL_SUPPRESS_SEND"] = False   
app.config["MAIL_DEBUG"] = False           

# --- Khởi tạo mail ---
mail.init_app(app)


#Đăng ký tất cả Blueprint sau khi app + mail đã init

from routes.auth_bp import auth_bp
from routes.register_bp import register_bp
from routes.salary_bp import salary_bp
from routes.update_absences_route import update_absences_bp
from routes.capture_photo_and_save import capture_photo_and_save
from routes.faces_bp import faces_bp
from routes.employee_bp import employee_bp
from routes.deleted_bp import deleted_bp
from routes.department_bp import department_bp
from routes.shift_bp import shift_bp
from routes.schedule_bp import schedule_bp
from routes.account_bp import account_bp 
from routes.reports_bp import reports_bp
from routes.history_bp import history_bp
from routes.dashboard_bp import dashboard_bp
from routes.qlpb_bp import qlpb_bp
from routes.attendance_bp import attendance_bp

# ===============================================
# 🧩 ĐĂNG KÝ TEMPLATE FILTER HIỂN THỊ LOẠI NHÂN VIÊN
# ===============================================
@app.template_filter('badge_loai_nv')
def badge_loai_nv(chucvu):
    if not chucvu:
        return '<span class="badge bg-secondary">Không xác định</span>'

    cv = chucvu.lower()
    if 'trưởng phòng' in cv:
        return '<span class="badge bg-warning text-dark"><i class="fas fa-star me-1"></i>Trưởng phòng</span>'
    elif 'phó phòng' in cv:
        return '<span class="badge bg-info text-dark"><i class="fas fa-user-tie me-1"></i>Phó phòng</span>'
    elif 'hr' in cv or 'nhân sự' in cv:
        return '<span class="badge bg-success"><i class="fas fa-user-tie me-1"></i>HR</span>'
    elif 'thực tập' in cv or 'intern' in cv:
        return '<span class="badge bg-secondary"><i class="fas fa-user-graduate me-1"></i>Thực tập sinh</span>'
    elif 'thử việc' in cv:
        return '<span class="badge bg-light text-dark"><i class="fas fa-hourglass-half me-1"></i>Thử việc</span>'
    elif 'sale' in cv or 'kinh doanh' in cv:
        return '<span class="badge bg-primary"><i class="fas fa-handshake me-1"></i>Nhân viên kinh doanh</span>'
    else:
        return '<span class="badge bg-dark"><i class="fas fa-user me-1"></i>Nhân viên</span>'


# --- Đăng ký blueprint ---
app.register_blueprint(auth_bp)
app.register_blueprint(register_bp)
app.register_blueprint(salary_bp)
app.register_blueprint(update_absences_bp)
app.register_blueprint(account_bp)
app.register_blueprint(faces_bp)
app.register_blueprint(employee_bp)
app.register_blueprint(deleted_bp)
app.register_blueprint(department_bp)
app.register_blueprint(shift_bp)
app.register_blueprint(schedule_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(history_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(qlpb_bp)
app.register_blueprint(attendance_bp)


ENABLE_SCHEDULER = False  

if ENABLE_SCHEDULER:
    from routes.scheduler import start_scheduler
    start_scheduler(app)

# Bộ lọc và hàm tiện ích chung

@app.template_filter('strftime')
def _jinja2_filter_datetime(value, format="%d/%m/%Y"):
    """Cho phép dùng {{ value|strftime('%d/%m/%Y') }} trong template"""
    if not value:
        return ""
    try:
        return value.strftime(format)
    except Exception:
        return str(value)

current_employee = {}

# Kết nối SQL Server

def get_sql_connection():
    conn = pyodbc.connect(
        "Driver={SQL Server};"
        "Server=MINHHOP\\SQLEXPRESS;"
        "Database=FaceID;"
        "UID=sa;PWD=123456"
    )
    cursor = conn.cursor()
    try:
        username = session.get('username') or session.get('user_id') or 'admin'
        cursor.execute("EXEC sys.sp_set_session_context @key=N'user', @value=?", (username,))
        conn.commit()
    except:
        pass 
    return conn


@app.route('/photos/<path:filename>')
def serve_photos(filename):
    """Cho phép Flask hiển thị ảnh từ thư mục photos/ (chỉ trả về ảnh thật, không dùng default.jpg)."""
    import os
    from flask import abort, send_from_directory

    photo_dir = os.path.join(os.getcwd(), 'photos')  
    file_path = os.path.join(photo_dir, filename)

    if not os.path.exists(file_path):
        return abort(404)

    return send_from_directory(photo_dir, filename)

def safe_date_format(value):
    """Chuyển đổi giá trị ngày (datetime hoặc string) thành định dạng dd/mm/yyyy"""
    if not value:
        return "—"
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, fmt).strftime("%d/%m/%Y")
            except ValueError:
                continue
        return value
    try:
        return value.strftime("%d/%m/%Y")
    except Exception:
        return str(value)

camera = None
def get_camera():
    global camera
    if camera is None or not camera.isOpened():
        camera = cv2.VideoCapture(0, cv2.CAP_MSMF) 
        if not camera.isOpened():
            print("Không mở được camera")
            return None
    return camera

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

# Trang chính

@app.route("/")
@app.route("/index")
def index():
    return render_template("index.html")

# HÀM SINH MÃ NHÂN VIÊN

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

# Trang chấm công

@app.route("/attendance")
def attendance():
   
    return render_template("attendance.html")

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

    # Lấy MaLLV tương ứng trong LichLamViec
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


@app.route("/settings", endpoint='settings')
@require_role("admin")
def settings_view():
    return "<h1>Trang Cài đặt (Settings)</h1>"

# Đăng xuất

@app.route("/logout")
def logout():
    session.clear()
    flash("Đã đăng xuất thành công!", "success")
    return redirect(url_for("login"))

@app.route("/get_current_employee")
def get_current_employee():
    """Trả về thông tin nhân viên hiện tại cho giao diện"""
    from routes.attendance_system import current_employee as att_emp
    print(f"📡 [DEBUG] current_employee = {att_emp}")
    if att_emp and att_emp.get("found"):
        return jsonify(att_emp)
    return jsonify({"found": False})

# API stream camera chấm công

from routes.attendance_system import load_known_faces, generate_frames

@app.route("/attendance_feed")
def attendance_feed():
    known_encodings, known_ids, known_names = load_known_faces()
    return Response(
        generate_frames(known_encodings, known_ids, known_names),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )

# Run app
if __name__ == "__main__":
    print("Server đang chạy tại: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)




