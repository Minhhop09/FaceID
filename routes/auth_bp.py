# ===============================================
# 📦 AUTH_BP — ĐĂNG NHẬP & KHÔI PHỤC MẬT KHẨU
# ===============================================
from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, current_app
)
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
from threading import Thread
import random, socket, time, secrets, os

from core.db_utils import get_sql_connection
from core.email_utils import send_email_notification
from config_google import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from core.add_employee import generate_ma_nv

# ===============================================
# ⚙️ KHỞI TẠO BLUEPRINT & BIẾN TOÀN CỤC
# ===============================================
auth_bp = Blueprint("auth_bp", __name__)
otp_expire_time = {}

# ===============================================
# 🔧 HÀM KHỞI TẠO GOOGLE LOGIN (GỌI TRONG app.py)
# ===============================================
def init_oauth(app):
    """Khởi tạo cấu hình OAuth cho Google."""
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth

@auth_bp.route("/login/google")
def login_google():
    oauth = current_app.extensions["oauth"]
    redirect_uri = url_for("auth_bp.authorize_google", _external=True)
    print("[DEBUG] Redirect URI gửi Google:", redirect_uri)
    return oauth.google.authorize_redirect(redirect_uri)

@auth_bp.route("/login/google/authorize")
def authorize_google():
    oauth = current_app.extensions["oauth"]
    print("[DEBUG] Callback query:", dict(request.args))

    # 1️⃣ Lấy token và thông tin người dùng từ Google
    token = oauth.google.authorize_access_token()
    user_info = oauth.google.get('https://www.googleapis.com/oauth2/v2/userinfo').json()
    print("[DEBUG] User info:", user_info)

    if not user_info:
        flash("Không lấy được thông tin tài khoản Google!", "danger")
        return redirect(url_for("auth_bp.login"))

    # 2️⃣ Kết nối CSDL
    conn = get_sql_connection()
    cursor = conn.cursor()

    email = user_info.get("email")
    name = user_info.get("name")
    picture = user_info.get("picture")

    # 3️⃣ Kiểm tra nhân viên có tồn tại chưa
    cursor.execute("SELECT MaNV FROM NhanVien WHERE Email = ?", (email,))
    row = cursor.fetchone()

    # 4️⃣ Nếu chưa có → tạo mới nhân viên
    if not row:
        # Sinh mã NV tự động (NV00001, NV00002, ...)
        cursor.execute("SELECT TOP 1 MaNV FROM NhanVien ORDER BY MaNV DESC")
        last = cursor.fetchone()
        if last and last[0]:
            num = int(last[0][2:]) + 1
        else:
            num = 1
        new_ma_nv = f"NV{num:05d}"

        cursor.execute("""
            INSERT INTO NhanVien (MaNV, HoTen, Email, ChucVu, TrangThai)
            VALUES (?, ?, ?, ?, 1)
        """, (new_ma_nv, name, email, "Nhân viên"))

        conn.commit()
        ma_nv = new_ma_nv
        print(f"[DEBUG] ➕ Đã tạo nhân viên mới: {ma_nv} ({email})")
    else:
        ma_nv = row[0]
        print(f"[DEBUG] ✅ Nhân viên tồn tại: {ma_nv} ({email})")

    # 5️⃣ Cập nhật session đăng nhập
    session.clear()
    session["user_id"] = user_info.get("id")
    session["username"] = email.split("@")[0]
    session["email"] = email
    session["hoten"] = name
    session["manv"] = ma_nv
    session["role"] = "nhanvien"
    session["roles"] = ("nhanvien",)
    session["avatar"] = picture

    conn.close()

    # 6️⃣ Flash & redirect
    flash("Đăng nhập bằng Google thành công!", "success")
    print("[SESSION AFTER GOOGLE LOGIN]:", dict(session))
    return redirect(url_for("employee_bp.employee_dashboard"))

# ==========================
# 1️⃣ ĐĂNG NHẬP HỆ THỐNG
# ==========================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        login_input = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not login_input or not password:
            flash("Vui lòng nhập đầy đủ thông tin đăng nhập!", "warning")
            return redirect(url_for("auth_bp.login"))

        conn = get_sql_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT tk.MaTK, tk.TenDangNhap, tk.TrangThai,
                   nv.MaNV, nv.HoTen, nv.Email, tk.MatKhauHash
            FROM TaiKhoan tk
            LEFT JOIN NhanVien nv ON tk.MaNV = nv.MaNV
            WHERE (tk.MaNV = ? OR nv.Email = ? OR tk.TenDangNhap = ?)
        """, (login_input, login_input, login_input))
        user = cursor.fetchone()

        if not user:
            flash("Không tìm thấy tài khoản!", "danger")
            conn.close()
            return redirect(url_for("auth_bp.login"))

        ma_tk, ten_dang_nhap, trang_thai, ma_nv, ho_ten, email, matkhau_db = user

        if not matkhau_db or not check_password_hash(matkhau_db, password):
            flash("Sai mật khẩu!", "danger")
            conn.close()
            return redirect(url_for("auth_bp.login"))

        if trang_thai != 1:
            flash("Tài khoản này đang bị khóa!", "warning")
            conn.close()
            return redirect(url_for("auth_bp.login"))

        # Lấy vai trò
        cursor.execute("""
            SELECT vt.TenVaiTro
            FROM TaiKhoan tk
            JOIN VaiTro vt ON tk.MaVT = vt.MaVT
            WHERE tk.MaTK = ?
        """, (ma_tk,))
        role_row = cursor.fetchone()
        conn.close()

        vai_tro = (role_row[0] if role_row else "NhanVien").strip().lower()

        # Lưu session
        session.clear()
        session["username"] = ten_dang_nhap or ma_nv or email
        session["role"] = vai_tro
        session["manv"] = ma_nv
        session["hoten"] = ho_ten
        session["email"] = email

        # Điều hướng theo vai trò
        if vai_tro == "admin":
            return redirect(url_for("admin_dashboard"))
        elif vai_tro == "hr":
            return redirect(url_for("dashboard_bp.hr_dashboard"))
        elif vai_tro == "quanlyphongban":
            return redirect(url_for("qlpb_bp.qlpb_dashboard"))
        elif vai_tro == "nhanvien":
            return redirect(url_for("employee_bp.employee_dashboard"))
        else:
            flash("⚠️ Vai trò không hợp lệ hoặc chưa được gán!", "warning")
            return redirect(url_for("auth_bp.login"))

    return render_template("login.html")


# ==========================
# 2️⃣ QUÊN MẬT KHẨU — GỬI OTP
# ==========================
@auth_bp.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        if not email:
            flash("Vui lòng nhập địa chỉ email!", "warning")
            return redirect(url_for("auth_bp.forgot_password"))

        conn = get_sql_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT MaNV, HoTen FROM NhanVien WHERE Email = ?", (email,))
        user = cursor.fetchone()
        if not user:
            flash("Không tìm thấy email trong hệ thống.", "danger")
            conn.close()
            return redirect(url_for("auth_bp.forgot_password"))

        ma_nv, ho_ten = user

        # Tạo mã OTP và lưu tạm
        otp = random.randint(100000, 999999)
        session["reset_otp"] = otp
        session["reset_email"] = email
        otp_expire_time[email] = datetime.now() + timedelta(minutes=5)

        subject = "🔐 Mã xác minh đặt lại mật khẩu FaceID"
        body = (
            f"Kính gửi {ho_ten},\n\n"
            f"Mã xác minh (OTP) của bạn là: {otp}\n"
            f"Mã này có hiệu lực trong 5 phút.\n\n"
            f"Trân trọng,\nHệ thống FaceID"
        )

        try:
            result = send_email_notification(email, subject, body)
            status = "Thành công" if result else "Lỗi gửi mail"
            print(f"📧 Đã gửi OTP đến {email} ({status})")
        except Exception as e:
            status = f"Lỗi: {str(e)[:80]}"
            print(f"❌ Gửi OTP thất bại cho {email}: {e}")

        cursor.execute("""
            INSERT INTO LichSuEmail (MaTK, EmailTo, LoaiThongBao, ThoiGian, TrangThai)
            SELECT TK.MaTK, NV.Email, N'Gửi OTP xác minh', GETDATE(), ?
            FROM TaiKhoan TK JOIN NhanVien NV ON TK.MaNV = NV.MaNV
            WHERE NV.Email = ?
        """, (status, email))
        conn.commit()
        conn.close()

        flash("✅ Mã xác minh đã được gửi đến email của bạn!", "success")
        return redirect(url_for("auth_bp.verify_otp"))

    return render_template("forgot_password.html")


# ==========================
# 3️⃣ XÁC MINH OTP
# ==========================
@auth_bp.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    if "reset_email" not in session or "reset_otp" not in session:
        flash("Phiên làm việc đã hết hạn, vui lòng nhập lại email.", "warning")
        return redirect(url_for("auth_bp.forgot_password"))

    if request.method == "POST":
        user_otp = request.form.get("otp", "").strip()
        real_otp = str(session.get("reset_otp"))
        email = session.get("reset_email")
        expire_time = otp_expire_time.get(email)

        if expire_time and datetime.now() > expire_time:
            flash("⚠️ Mã OTP đã hết hạn. Vui lòng yêu cầu mã mới.", "warning")
            session.pop("reset_otp", None)
            session.pop("reset_email", None)
            return redirect(url_for("auth_bp.forgot_password"))

        if user_otp == real_otp:
            flash("✅ Xác minh thành công! Vui lòng đặt lại mật khẩu mới.", "success")
            return redirect(url_for("auth_bp.reset_password"))
        else:
            flash("Mã OTP không chính xác, vui lòng thử lại.", "danger")

    return render_template("verify_otp.html")


# ==========================
# 4️⃣ ĐẶT LẠI MẬT KHẨU (sửa triệt để lỗi context)
# ==========================
@auth_bp.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    if "reset_email" not in session:
        flash("Phiên làm việc đã hết hạn, vui lòng nhập lại email.", "warning")
        return redirect(url_for("auth_bp.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password")
        confirm = request.form.get("confirm")

        if not password or not confirm:
            flash("Vui lòng nhập đầy đủ mật khẩu!", "warning")
            return render_template("reset_password.html")

        if password != confirm:
            flash("Mật khẩu nhập lại không khớp.", "danger")
            return render_template("reset_password.html")

        email = session["reset_email"]
        hashed_pw = generate_password_hash(password, method="scrypt")

        conn = get_sql_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT MaNV, HoTen FROM NhanVien WHERE Email = ?", (email,))
        row = cursor.fetchone()
        if not row:
            flash("Không tìm thấy nhân viên tương ứng với email này!", "danger")
            conn.close()
            return render_template("reset_password.html")

        ma_nv, ho_ten = row
        ip_address = request.remote_addr or "Unknown"
        device_id = socket.gethostname() or "Unknown"

        try:
            cursor.execute("""
                UPDATE TaiKhoan SET MatKhauHash = ? WHERE MaNV = ?
            """, (hashed_pw, ma_nv))

            cursor.execute("""
                INSERT INTO LichSuThayDoi
                    (TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                     GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien,
                     IPAddress, DeviceID, Scope)
                VALUES
                    (N'TaiKhoan', ?, N'Đặt lại mật khẩu', N'MatKhau',
                     N'Ẩn', N'Ẩn', GETDATE(), ?, ?, ?, N'Người dùng')
            """, (ma_nv, email, ip_address, device_id))

            cursor.execute("""
                INSERT INTO LichSuEmail (MaTK, EmailTo, LoaiThongBao, ThoiGian, TrangThai)
                SELECT TK.MaTK, NV.Email, N'Đặt lại mật khẩu thành công', GETDATE(), N'Đang gửi'
                FROM TaiKhoan TK JOIN NhanVien NV ON TK.MaNV = NV.MaNV
                WHERE NV.Email = ?
            """, (email,))
            conn.commit()
            conn.close()

            # ✅ Tạo Flask app thực
            app_obj = current_app._get_current_object()

            def send_reset_email_background(ma_nv_thr, ho_ten_thr, email_thr):
                with app_obj.app_context():
                    time.sleep(0.3)
                    local_conn = get_sql_connection()
                    local_cursor = local_conn.cursor()

                    subject = "✅ Xác nhận đặt lại mật khẩu FaceID thành công"
                    body = (
                        f"Kính gửi {ho_ten_thr},\n\n"
                        f"Mật khẩu cho tài khoản của bạn (Mã NV: {ma_nv_thr}) đã được đặt lại thành công.\n"
                        f"Nếu đây không phải là bạn, vui lòng liên hệ phòng nhân sự ngay lập tức.\n\n"
                        f"Trân trọng,\nHệ thống FaceID"
                    )

                    try:
                        send_email_notification(email_thr, subject, body)
                        status = "Thành công"
                    except Exception as e:
                        status = f"Lỗi: {str(e)[:80]}"

                    local_cursor.execute("""
                        UPDATE LichSuEmail
                        SET TrangThai = ?
                        WHERE EmailTo = ?
                          AND LoaiThongBao = N'Đặt lại mật khẩu thành công'
                          AND CAST(ThoiGian AS DATE) = CAST(GETDATE() AS DATE)
                    """, (status, email_thr))
                    local_conn.commit()
                    local_conn.close()
                    print(f"📩 Đã gửi xác nhận đặt lại mật khẩu đến {email_thr} ({status})")

            Thread(target=send_reset_email_background, args=(ma_nv, ho_ten, email), daemon=True).start()

            session.pop("reset_email", None)
            session.pop("reset_otp", None)
            flash("✅ Đặt lại mật khẩu thành công! Bạn có thể đăng nhập ngay.", "success")
            return redirect(url_for("auth_bp.login"))

        except Exception as e:
            conn.rollback()
            conn.close()
            flash(f"Lỗi khi đặt lại mật khẩu: {e}", "danger")

    return render_template("reset_password.html")
