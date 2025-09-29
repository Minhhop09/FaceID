from flask import Flask, render_template, request, redirect, url_for, flash, Response, session, jsonify
import pyodbc
import hashlib
import atexit
from datetime import datetime
import cv2
from add_employee import generate_ma_nv, add_new_employee
from db_utils import get_phongbans
from capture_photo_and_save import capture_photo_and_save
from encode_save import encode_and_save
from attendance_system import process_frame, load_known_faces, generate_frames, record_attendance, current_employee as att_current_employee
from db_utils import get_sql_connection
from attendance_system import current_employee
import manage_department
import manage_shift
import manage_account
import reports

# ======================
# Config Flask
# ======================
app = Flask(__name__)
app.secret_key = "faceid_secret"

# ======================
# SQL Connection
# ======================
def get_sql_connection():
    return pyodbc.connect(
        "DRIVER={SQL Server};"
        "SERVER=MINHHOP\\SQLEXPRESS;"
        "DATABASE=FaceID;"
        "UID=sa;PWD=123456"
    )

# ======================
# Camera global (singleton)
# ======================
camera = None
def get_camera():
    global camera
    if camera is None or not camera.isOpened():
        camera = cv2.VideoCapture(0, cv2.CAP_MSMF) 
        if not camera.isOpened():
            print("❌ Không mở được camera")
            return None
    return camera

# ======================
# Face encodings
# ======================
known_encodings, known_ids, known_names = load_known_faces()

# ====================
# Camera stream CHẤM CÔNG
# ====================
@app.route('/video_feed')
def video_feed():
    encodings, ids, names = load_known_faces()
    return Response(
        generate_frames(encodings, ids, names),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

# ====================
# Camera stream ĐĂNG KÝ
# ====================
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

# ======================
# Chấm công thủ công
# ======================
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

# ======================
# Login
# ======================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        password_hash = hashlib.sha256(password.encode()).hexdigest()

        conn = get_sql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MaTK, TenDangNhap, VaiTro, TrangThai 
            FROM TaiKhoan 
            WHERE TenDangNhap=? AND MatKhauHash=?
        """, (username, password_hash))
        user = cursor.fetchone()
        conn.close()

        if user:
            if user.TrangThai != 1:
                flash("❌ Tài khoản đang bị khóa!", "danger")
                return redirect(url_for("login"))

            session["username"] = user.TenDangNhap
            session["role"] = user.VaiTro
            return redirect(url_for("index"))
        else:
            flash("❌ Sai tên đăng nhập hoặc mật khẩu", "danger")
            return redirect(url_for("login"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("username", None)
    session.pop("role", None)
    return redirect(url_for("login"))

# ======================
# Trang chính
# ======================
@app.route("/")
@app.route("/index")
def index():
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", username=session["username"])

# ======================
# Trang đăng ký nhân viên
# ======================
@app.route("/register", methods=["GET", "POST"])
def register():
    if "username" not in session:
        return redirect(url_for("login"))

    phongbans = get_phongbans()

    if request.method == "POST":
        hoten = request.form.get("HoTen", "").strip()
        email = request.form.get("Email", "").strip()
        sdt = request.form.get("SDT", "").strip()
        gioitinh_input = request.form.get("GioiTinh", "").strip().lower()
        ngaysinh = request.form.get("NgaySinh", "").strip()
        diachi = request.form.get("DiaChi", "").strip()
        ma_pb = request.form.get("PhongBan", "").strip()

        if not hoten or not email or not ma_pb:
            flash("❌ Vui lòng điền đầy đủ thông tin", "danger")
            return redirect(url_for("register"))

        gioitinh = 1 if gioitinh_input == "nam" else 0 if gioitinh_input == "nữ" else None
        if gioitinh is None:
            flash("❌ Giới tính không hợp lệ", "danger")
            return redirect(url_for("register"))

        conn = get_sql_connection()
        cursor = conn.cursor()
        try:
            ma_nv = generate_ma_nv(cursor, ma_pb)
            ma_nv = add_new_employee(cursor, conn, ma_nv, hoten, email, ma_pb,
                                     sdt, gioitinh, ngaysinh, diachi)

            # Chụp ảnh nhân viên
            image_path = capture_photo_and_save(ma_nv)

            if image_path:
                encode_and_save(ma_nv, image_path, conn)
                global known_encodings, known_ids, known_names
                known_encodings, known_ids, known_names = load_known_faces()

            flash("✅ Nhân viên + FaceID đã đăng ký thành công!", "success")

        except Exception as e:
            flash(f"❌ Lỗi khi thêm nhân viên: {e}", "danger")
        finally:
            conn.close()

        return redirect(url_for("register"))

    return render_template("register.html", phongbans=phongbans)

# ======================
# API lấy nhân viên gần nhất
# ======================
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
            "TrangThai": current_employee.get("TrangThai")
        })
    return jsonify({"found": False})

# ======================
# Trang chấm công
# ======================
@app.route("/attendance")
def attendance():
    if "username" not in session:
        return redirect(url_for("login"))
    return render_template("attendance.html")

# ======================
# Chấm công thủ công
# ======================
@app.route("/manual_attendance", methods=["POST"])
def manual_attendance():
    ma_nv = request.form.get("ma_nv")
    if ma_nv:
        try:
            record_manual_attendance(ma_nv)
            flash("✅ Chấm công thành công!", "success")
        except Exception as e:
            flash(f"❌ Lỗi khi chấm công: {e}", "danger")
    else:
        flash("❌ Không tìm thấy nhân viên để chấm công", "danger")
    return redirect(url_for("attendance"))

@app.route("/current_employee")
def current_employee_api():
    return jsonify(current_employee if current_employee else {"error": "No employee"})

# ======================
# Trang Admin
# ======================
@app.route('/admin')
def admin_dashboard():
    if 'role' in session and session['role'] == 'admin':
        return render_template('admin.html')
    else:
        flash("Bạn không có quyền truy cập!", "danger")
        return redirect(url_for('login'))

# ======================
# Giải phóng camera khi app dừng
# ======================
def close_camera():
    global camera
    if camera and camera.isOpened():
        camera.release()
        print("✅ Camera đã được giải phóng")

atexit.register(close_camera)

@app.teardown_appcontext
def cleanup(exception=None):
    if camera and camera.isOpened():
        camera.release()

# ======================
# QUẢN LÝ PHÒNG BAN
# ======================

# --- Danh sách phòng ban ---
@app.route("/departments")
def departments():
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MaPB, TenPB FROM PhongBan")
    departments = cursor.fetchall()
    conn.close()
    return render_template("departments.html", departments=departments)

# --- Thêm phòng ban ---
@app.route("/departments/add", methods=["POST"])
def add_department():
    ten_pb = request.form["ten_pb"]
    if not ten_pb.strip():
        flash("Tên phòng ban không được để trống!", "error")
        return redirect(url_for("departments"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO PhongBan (TenPB) VALUES (?)", (ten_pb,))
    conn.commit()
    conn.close()

    flash("Thêm phòng ban thành công!", "info")
    return redirect(url_for("departments"))

# --- Chỉnh sửa phòng ban ---
@app.route("/departments/edit/<ma_pb>", methods=["GET", "POST"])
def edit_department(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        ten_pb = request.form["ten_pb"].strip()
        if not ten_pb:
            flash("Tên phòng ban không được để trống!", "error")
            return redirect(url_for("edit_department", ma_pb=ma_pb))

        cursor.execute("UPDATE PhongBan SET TenPB = ? WHERE MaPB = ?", (ten_pb, ma_pb))
        conn.commit()
        conn.close()
        flash("Cập nhật phòng ban thành công!", "info")
        return redirect(url_for("departments"))
    else:
        cursor.execute("SELECT MaPB, TenPB FROM PhongBan WHERE MaPB = ?", (ma_pb,))
        row = cursor.fetchone()
        conn.close()
        if row:
            department = {"ma_pb": row[0], "ten_pb": row[1]}  # chuyển thành dict
            return render_template("departments_edit.html", department=department)
        else:
            flash("Không tìm thấy phòng ban!", "error")
            return redirect(url_for("departments"))

# --- Xóa phòng ban ---
@app.route("/departments/delete/<ma_pb>", methods=["POST"])
def delete_department(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM PhongBan WHERE MaPB = ?", (ma_pb,))
    conn.commit()
    conn.close()
    flash("Xóa phòng ban thành công!", "info")
    return redirect(url_for("departments"))


# ======================
# QUẢN LÝ CA LÀM
# ======================
@app.route("/shifts")
def shifts():
    data = manage_shift.get_shifts()
    return render_template("shifts.html", shifts=data)

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

@app.route("/edit_shift/<ma_ca>", methods=["GET", "POST"])
def edit_shift(ma_ca):
    if request.method == "POST":
        gio_bd = request.form["gio_bat_dau"]
        gio_kt = request.form["gio_ket_thuc"]
        manage_shift.update_shift(ma_ca, gio_bd, gio_kt)
        flash("Cập nhật ca làm thành công!", "success")
        return redirect(url_for("shifts"))
    return render_template("edit_shift.html", ma_ca=ma_ca)

@app.route("/delete_shift/<ma_ca>")
def delete_shift(ma_ca):
    manage_shift.delete_shift(ma_ca)
    flash("Xóa ca làm thành công!", "danger")
    return redirect(url_for("shifts"))


# ======================
# QUẢN LÝ TÀI KHOẢN
# ======================
@app.route("/accounts")
def accounts():
    data = manage_account.get_accounts()
    return render_template("accounts.html", accounts=data)

@app.route("/add_account", methods=["GET", "POST"])
def add_account():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        role = request.form["role"]
        manage_account.add_account(username, password, role)
        flash("Thêm tài khoản thành công!", "success")
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
@app.route("/reports", methods=["GET", "POST"])
def reports_view():
    data_attendance, data_department, data_shift = [], [], []
    if request.method == "POST":
        start_date = request.form["start_date"]
        end_date = request.form["end_date"]
        data_attendance = reports.attendance_report(start_date, end_date)
    data_department = reports.department_report()
    data_shift = reports.shift_report()
    return render_template("reports.html",
                           attendance=data_attendance,
                           departments=data_department,
                           shifts=data_shift)

# ======================
# Run app
# ======================
if __name__ == "__main__":
    app.run(debug=True)


