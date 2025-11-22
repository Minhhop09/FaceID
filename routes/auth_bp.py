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
import pyotp
from core.log_utils import log_action
from core.db_utils import get_sql_connection
from core.email_utils import notify_attendance
from config_google import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
from core.add_employee import generate_ma_nv
import pyotp, qrcode, io, base64
# ===============================================
# ⚙️ KHỞI TẠO BLUEPRINT & BIẾN TOÀN CỤC
# ===============================================
auth_bp = Blueprint("auth_bp", __name__)
otp_expire_time = {}

def _fetch_user_by_username(username: str):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MaTK, TenDangNhap, MatKhauHash, Email, TwoFA_Enabled, TOTP_Secret, VaiTro, TrangThai, MaNV
        FROM TaiKhoan WHERE TenDangNhap = ?
    """, (username,))
    row = cursor.fetchone()
    conn.close()
    return row

def _fetch_user_by_id(matk: int):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MaTK, TenDangNhap, Email, TwoFA_Enabled, TOTP_Secret, VaiTro, TrangThai, MaNV
        FROM TaiKhoan WHERE MaTK = ?
    """, (matk,))
    row = cursor.fetchone()
    conn.close()
    return row

# ============================================================
# 🔐 XÁC THỰC HAI LỚP (2FA - TOTP GOOGLE AUTHENTICATOR)
# ============================================================

import pyotp, qrcode, io, base64
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from core.db_utils import get_sql_connection
from core.log_utils import log_action
from core.email_utils import send_email_notification  # nếu bạn có module riêng


# ============================================================
# ⚙️ BẬT XÁC THỰC 2FA
# ============================================================
@auth_bp.route("/enable_2fa", methods=["GET", "POST"])
def enable_2fa():
    """Bật xác thực hai lớp (2FA) bằng Google Authenticator."""
    if "user_id" not in session:
        flash("Vui lòng đăng nhập trước khi bật 2FA.", "warning")
        return redirect(url_for("auth_bp.login"))

    ma_tk = session["user_id"]
    email = session.get("email", "N/A")
    hoten = session.get("hoten", "Người dùng")
    ip = request.remote_addr or "Unknown"
    device = request.user_agent.string[:300] if request.user_agent else "Unknown"

    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TwoFA_Enabled, TOTP_Secret FROM TaiKhoan WHERE MaTK = ?", (ma_tk,))
    current = cursor.fetchone()

    if not current:
        flash("Không tìm thấy tài khoản trong hệ thống!", "danger")
        return redirect(url_for("auth_bp.login"))

    current_enabled, current_secret = current

    # ===========================================
    # 🧭 GET: Hiển thị QR và lưu secret tạm
    # ===========================================
    if request.method == "GET":
        if current_enabled:
            return render_template("security.html", twofa_enabled=True, qr_b64=None, secret=None)

        import pyotp, qrcode, base64, io
        secret = pyotp.random_base32()
        session["temp_2fa_secret"] = secret  # 🔹 lưu tạm secret
        totp = pyotp.TOTP(secret)
        qr_uri = totp.provisioning_uri(name=email, issuer_name="FaceID System")

        qr_img = qrcode.make(qr_uri)
        buffer = io.BytesIO()
        qr_img.save(buffer, format="PNG")
        qr_b64 = base64.b64encode(buffer.getvalue()).decode()

        return render_template("security.html", twofa_enabled=False, qr_b64=qr_b64, secret=secret)

    # ===========================================
    # 🧭 POST: Xác minh mã OTP
    # ===========================================
    otp = (request.form.get("otp") or "").strip()
    secret = session.get("temp_2fa_secret")  # 🔹 lấy lại secret từ session

    if not otp or not secret:
        flash("Thiếu mã OTP hoặc secret key!", "danger")
        return redirect(url_for("auth_bp.enable_2fa"))

    import pyotp
    totp = pyotp.TOTP(secret)
    if totp.verify(otp, valid_window=1):
        cursor.execute("""
            UPDATE TaiKhoan
            SET TwoFA_Enabled = 1, TOTP_Secret = ?
            WHERE MaTK = ?
        """, (secret, ma_tk))
        conn.commit()

        # Xóa secret tạm
        session.pop("temp_2fa_secret", None)

        flash("✅ Đã bật xác thực hai lớp thành công!", "success")
        log_action("2FA_ENABLE", f"Bật 2FA cho {email} từ {ip} | {device}", "Thành công", "Bảo mật", ma_tk)

        # 📧 Gửi email thông báo
        try:
            subject = "🔐 Bật xác thực hai lớp (2FA) thành công"
            body = (
                f"Kính gửi {hoten},\n\n"
                f"Tài khoản {email} của bạn đã bật xác thực hai lớp (2FA) thành công.\n"
                f"Nếu bạn không thực hiện thao tác này, vui lòng liên hệ quản trị viên ngay lập tức.\n\n"
                f"Trân trọng,\nHệ thống FaceID"
            )
            send_email_notification(email, subject, body)
        except Exception as e:
            print(f"[EMAIL WARN] Không gửi được email bật 2FA: {e}")

        # ✅ Điều hướng về dashboard tương ứng
        role = session.get("role")
        if isinstance(role, (list, tuple)):
            role = role[0]

        if role == "admin":
            return redirect(url_for("admin_dashboard"))
        elif role == "hr":
            return redirect(url_for("dashboard_bp.hr_dashboard")
)
        elif role in ("quanlyphongban", "qlpb"):
            return redirect(url_for("qlpb_bp.qlpb_dashboard"))
        elif role == "nhanvien":
            return redirect(url_for("employee_bp.employee_dashboard"))
        else:
            return redirect(url_for("auth_bp.security"))

    else:
        flash("❌ Mã OTP không đúng hoặc đã hết hạn. Vui lòng thử lại.", "danger")
        return redirect(url_for("auth_bp.enable_2fa"))

# ============================================================
# 🔐 XÁC MINH 2FA KHI ĐĂNG NHẬP
# ============================================================
@auth_bp.route("/verify_2fa", methods=["GET", "POST"])
def verify_2fa():
    """Xác minh mã OTP khi đăng nhập bằng Google hoặc tài khoản thường."""
    if "pending_2fa_user_id" not in session:
        flash("Phiên đăng nhập không hợp lệ hoặc đã hết hạn.", "warning")
        return redirect(url_for("auth_bp.login"))

    ma_tk = session["pending_2fa_user_id"]

    # --- Giao diện nhập OTP ---
    if request.method == "GET":
        return render_template("verify_2fa_login.html")

    # --- POST: xác minh mã OTP ---
    otp = (request.form.get("otp") or "").strip()
    if not otp:
        flash("Vui lòng nhập mã OTP!", "danger")
        return redirect(url_for("auth_bp.verify_2fa"))

    # 🔹 Mở kết nối SQL
    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🔹 Lấy dữ liệu tài khoản
    cursor.execute("""
        SELECT MaNV, VaiTro, TenDangNhap, TOTP_Secret 
        FROM TaiKhoan 
        WHERE MaTK = ?
    """, (ma_tk,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("Không tìm thấy tài khoản!", "danger")
        return redirect(url_for("auth_bp.login"))

    ma_nv, vaitro, tendn, secret = row
    vaitro = (vaitro or session.get("pending_role") or "nhanvien").lower()

    # 🔹 Xác minh mã OTP
    import pyotp
    totp = pyotp.TOTP(secret)
    if totp.verify(otp, valid_window=1):
        # ✅ Thành công → lưu lại session đăng nhập
        session["user_id"] = ma_tk
        session["manv"] = ma_nv
        session["role"] = vaitro
        session["roles"] = (vaitro,)
        session["username"] = tendn   # 🟢 Dùng cho template {{ session['username'] }}
        session.pop("pending_2fa_user_id", None)
        session.pop("pending_role", None)

        flash("✅ Đăng nhập thành công (2FA xác thực)!", "success")
        log_action("2FA_VERIFY", f"Xác minh OTP thành công ({vaitro})", "Thành công", "Bảo mật", ma_tk)

        conn.close()  # 🔒 Đóng kết nối đúng lúc

        # ✅ Điều hướng đúng dashboard theo vai trò
        if vaitro == "admin":
            return redirect(url_for("admin_dashboard"))
        elif vaitro == "hr":
            return redirect(url_for("dashboard_bp.hr_dashboard"))
        elif vaitro in ("quanlyphongban", "qlpb"):
            return redirect(url_for("qlpb_bp.qlpb_dashboard"))
        else:
            return redirect(url_for("employee_bp.employee_dashboard"))

    else:
        conn.close()
        flash("❌ Mã OTP không đúng hoặc đã hết hạn!", "danger")
        log_action("2FA_VERIFY", "Nhập sai OTP khi đăng nhập", "Thất bại", "Bảo mật", ma_tk)
        return redirect(url_for("auth_bp.verify_2fa"))


# ============================================================
# 🚫 TẮT XÁC THỰC 2FA
# ============================================================
@auth_bp.route("/disable_2fa", methods=["POST"])
def disable_2fa():
    """Tắt xác thực hai lớp (2FA) cho tài khoản hiện tại."""
    if "user_id" not in session:
        flash("Vui lòng đăng nhập trước khi tắt 2FA.", "warning")
        return redirect(url_for("auth_bp.login"))

    ma_tk = session["user_id"]
    email = session.get("email", "N/A")
    hoten = session.get("hoten", "Người dùng")
    ip = request.remote_addr or "Unknown"
    device = request.user_agent.string[:300] if request.user_agent else "Unknown"

    conn = None
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT TwoFA_Enabled FROM TaiKhoan WHERE MaTK = ?", (ma_tk,))
        row = cursor.fetchone()

        if not row:
            flash("Không tìm thấy tài khoản trong hệ thống!", "danger")
            return redirect(url_for("auth_bp.security"))

        if row[0] == 0:
            flash("⚠️ Tài khoản của bạn hiện chưa bật 2FA.", "warning")
            return redirect(url_for("auth_bp.security"))

        cursor.execute("""
            UPDATE TaiKhoan
            SET TwoFA_Enabled = 0, TOTP_Secret = NULL
            WHERE MaTK = ?
        """, (ma_tk,))
        conn.commit()

        flash("🔓 Đã tắt xác thực hai lớp cho tài khoản của bạn.", "info")
        log_action("2FA_DISABLE", f"Tắt 2FA cho {email} từ {ip} | {device}", "Thành công", "Bảo mật", ma_tk)

        try:
            subject = "🔓 Đã tắt xác thực hai lớp (2FA)"
            body = (
                f"Kính gửi {hoten},\n\n"
                f"Tài khoản {email} của bạn đã tắt xác thực hai lớp.\n"
                f"Nếu bạn KHÔNG thực hiện hành động này, hãy đổi mật khẩu ngay và báo cho quản trị viên.\n\n"
                f"Thân mến,\nHệ thống FaceID"
            )
            send_email_notification(email, subject, body)
        except Exception as e:
            print(f"[EMAIL WARN] Không gửi được email tắt 2FA: {e}")

        return render_template("security.html", twofa_enabled=False, qr_b64=None, secret=None)

    except Exception as e:
        import traceback
        traceback.print_exc()
        if conn:
            try:
                conn.rollback()
            except Exception as ex:
                print(f"[ROLLBACK_WARN] {ex}")
        log_action("2FA_DISABLE", f"Lỗi khi tắt 2FA: {e}", "Thất bại", "Bảo mật", ma_tk)
        flash(f"Lỗi khi tắt 2FA: {e}", "danger")
        return redirect(url_for("auth_bp.security"))

    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

# ============================================================
# ⚙️ TRANG CÀI ĐẶT BẢO MẬT (HIỂN THỊ TRẠNG THÁI 2FA)
# ============================================================
@auth_bp.route("/security")
def security():
    if "user_id" not in session:
        return redirect(url_for("auth_bp.login"))

    ma_tk = session["user_id"]
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TwoFA_Enabled FROM TaiKhoan WHERE MaTK = ?", (ma_tk,))
    row = cursor.fetchone()
    conn.close()

    twofa_enabled = bool(row and row[0])
    return render_template("security.html", twofa_enabled=twofa_enabled, qr_b64=None, secret=None)

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

    conn = None
    try:
        # 1️⃣ Lấy token & thông tin người dùng từ Google
        token = oauth.google.authorize_access_token()
        user_info = oauth.google.get("https://www.googleapis.com/oauth2/v2/userinfo").json()
        print("[DEBUG] User info:", user_info)

        if not user_info:
            flash("Không lấy được thông tin tài khoản Google!", "danger")
            return redirect(url_for("auth_bp.login"))

        email = user_info.get("email")
        name = user_info.get("name")
        picture = user_info.get("picture")

        conn = get_sql_connection()
        cursor = conn.cursor()

        # 2️⃣ Kiểm tra nhân viên đã tồn tại chưa
        cursor.execute("SELECT MaNV FROM NhanVien WHERE Email = ?", (email,))
        nv_row = cursor.fetchone()

        if nv_row:
            ma_nv = nv_row[0]
            print(f"[DEBUG] ✅ Nhân viên tồn tại: {ma_nv} ({email})")

            # Lấy tài khoản tương ứng
            cursor.execute("""
                SELECT MaTK, TrangThai, DaDangKyKhuonMat, TwoFA_Enabled, TOTP_Secret, VaiTro, MaVT
                FROM TaiKhoan WHERE MaNV = ?
            """, (ma_nv,))
            acc = cursor.fetchone()

            if not acc:
                password_hash = generate_password_hash("123456", method="scrypt")
                cursor.execute("""
                    INSERT INTO TaiKhoan (TenDangNhap, MatKhauHash, VaiTro, MaVT, TrangThai, MaNV, DaDangKyKhuonMat, NgayTao)
                    VALUES (?, ?, ?, ?, 1, ?, 0, GETDATE())
                """, (ma_nv, password_hash, "nhanvien", 4, ma_nv))
                conn.commit()
                acc = (None, 1, 0, 0, None, "nhanvien", 4)
                print(f"[DEBUG] 🔑 Tạo tài khoản mới cho {ma_nv}")

        else:
            # 3️⃣ Nếu chưa có → tạo mới nhân viên + tài khoản
            cursor.execute("SELECT TOP 1 MaNV FROM NhanVien ORDER BY MaNV DESC")
            last = cursor.fetchone()
            num = int(last[0][2:]) + 1 if last and last[0] else 1
            ma_nv = f"NV{num:05d}"

            cursor.execute("""
                INSERT INTO NhanVien (MaNV, HoTen, Email, ChucVu, TrangThai)
                VALUES (?, ?, ?, ?, 1)
            """, (ma_nv, name, email, "Nhân viên"))

            password_hash = generate_password_hash("123456", method="scrypt")
            cursor.execute("""
                INSERT INTO TaiKhoan (TenDangNhap, MatKhauHash, VaiTro, MaVT, TrangThai, MaNV, DaDangKyKhuonMat, NgayTao)
                VALUES (?, ?, ?, ?, 1, ?, 0, GETDATE())
            """, (ma_nv, password_hash, "nhanvien", 4, ma_nv))
            conn.commit()
            acc = (None, 1, 0, 0, None, "nhanvien", 4)
            print(f"[DEBUG] ➕ Đã tạo nhân viên & tài khoản mới: {ma_nv} ({email})")

        # 4️⃣ Lấy thông tin tài khoản
        ma_tk = acc[0] if acc[0] else None
        trang_thai = acc[1]
        da_km = acc[2]
        twofa_enabled = acc[3]
        totp_secret = acc[4]
        vaitro = acc[5]
        ma_vt = acc[6]

        # 5️⃣ Kiểm tra trạng thái
        if trang_thai != 1:
            flash("Tài khoản Google của bạn bị khóa trong hệ thống!", "warning")
            return redirect(url_for("auth_bp.login"))

        # 6️⃣ Lưu session
        session.clear()
        session["username"] = email.split("@")[0]
        session["email"] = email
        session["hoten"] = name
        session["avatar"] = picture
        session["manv"] = ma_nv
        session["user_id"] = ma_tk
        session["role"] = vaitro
        session["roles"] = (vaitro,)

        # 7️⃣ Ghi log
        from core.log_utils import log_action
        ip = request.remote_addr or "Unknown"
        device = request.user_agent.string[:300] if request.user_agent else "Unknown"
        log_action("LOGIN_GOOGLE", f"Đăng nhập Google từ {ip} | {device}", "Thành công", "Bảo mật", ma_tk)

        # 8️⃣ Nếu bật 2FA → yêu cầu nhập mã OTP
        if twofa_enabled and totp_secret:
            session["pending_2fa_user_id"] = ma_tk
            flash("🔐 Tài khoản có bật xác thực hai lớp. Vui lòng nhập mã OTP.", "info")
            return redirect(url_for("auth_bp.verify_2fa"))

        # 9️⃣ Nếu chưa bật 2FA → yêu cầu cấu hình bảo mật
        if not twofa_enabled or not totp_secret:
            flash("⚙️ Vui lòng bật xác thực hai lớp (2FA) để bảo mật tài khoản của bạn.", "info")
            return redirect(url_for("auth_bp.security"))

        # 🔟 Kiểm tra khuôn mặt
        if not da_km:
            cursor.execute("SELECT COUNT(*) FROM KhuonMat WHERE MaNV = ?", (ma_nv,))
            face_count = cursor.fetchone()[0]
            if face_count > 0:
                cursor.execute("""
                    UPDATE TaiKhoan
                    SET DaDangKyKhuonMat = 1
                    WHERE MaNV = ?
                """, (ma_nv,))
                conn.commit()
                print(f"[AUTO-FIX] ✅ Đã có khuôn mặt → cập nhật DaDangKyKhuonMat = 1 cho {ma_nv}")
            else:
                flash("🧑‍💻 Tài khoản đã xác thực. Vui lòng đăng ký khuôn mặt để hoàn tất.", "info")
                return redirect(url_for("register_bp.register"))

        # 11️⃣ Thành công → điều hướng theo vai trò
        if vaitro == "admin":
            flash("👑 Chào mừng Admin!", "success")
            return redirect(url_for("admin_dashboard"))
        elif vaitro == "hr":
            flash("📋 Chào mừng Nhân sự!", "success")
            return redirect(url_for("dashboard_bp.hr_dashboard")
)
        elif vaitro in ("quanlyphongban", "qlpb"):
            flash("🏢 Chào mừng Quản lý phòng ban!", "success")
            return redirect(url_for("qlpb_bp.qlpb_dashboard"))
        else:
            flash("✅ Đăng nhập bằng Google thành công!", "success")
            return redirect(url_for("employee_bp.employee_dashboard"))

    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            if conn:
                conn.rollback()
        except Exception as ex:
            print(f"[ROLLBACK_WARN] {ex}")
        try:
            from core.log_utils import log_action
            log_action("LOGIN_GOOGLE", f"Lỗi khi xử lý đăng nhập Google: {e}", "Thất bại", "Bảo mật")
        except Exception:
            pass
        flash(f"Lỗi khi xử lý đăng nhập Google: {e}", "danger")
        return redirect(url_for("auth_bp.login"))

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass

# ==========================
# 1️⃣ ĐĂNG NHẬP HỆ THỐNG (Thường)
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

        # 🔍 Lấy thông tin tài khoản và vai trò
        cursor.execute("""
            SELECT tk.MaTK, tk.TenDangNhap, tk.TrangThai, 
                   nv.MaNV, nv.HoTen, nv.Email, tk.MatKhauHash,
                   tk.TwoFA_Enabled, tk.TOTP_Secret, tk.DaDangKyKhuonMat, vt.TenVaiTro
            FROM TaiKhoan tk
            LEFT JOIN NhanVien nv ON tk.MaNV = nv.MaNV
            LEFT JOIN VaiTro vt ON tk.MaVT = vt.MaVT
            WHERE (tk.MaNV = ? OR nv.Email = ? OR tk.TenDangNhap = ?)
        """, (login_input, login_input, login_input))
        user = cursor.fetchone()

        if not user:
            flash("Không tìm thấy tài khoản!", "danger")
            conn.close()
            return redirect(url_for("auth_bp.login"))

        ma_tk, ten_dang_nhap, trang_thai, ma_nv, ho_ten, email, matkhau_db, twofa_enabled, totp_secret, da_km, vai_tro = user
        vai_tro = (vai_tro or "nhanvien").strip().lower()

        # 🔒 Kiểm tra mật khẩu
        if not matkhau_db or not check_password_hash(matkhau_db, password):
            flash("Sai mật khẩu!", "danger")
            log_action("LOGIN", f"Đăng nhập thất bại - Sai mật khẩu ({login_input})", "Thất bại", "Bảo mật")
            conn.close()
            return redirect(url_for("auth_bp.login"))

        # 🚫 Kiểm tra trạng thái tài khoản
        if trang_thai != 1:
            flash("Tài khoản này đang bị khóa!", "warning")
            log_action("LOGIN", f"Đăng nhập thất bại - Tài khoản bị khóa ({login_input})", "Thất bại", "Bảo mật")
            conn.close()
            return redirect(url_for("auth_bp.login"))

        # 🧠 Ghi log đăng nhập thành công
        ip = request.remote_addr or "Unknown"
        device = request.user_agent.string[:300] if request.user_agent else "Unknown"
        log_action("LOGIN", f"Đăng nhập thành công từ {ip} | {device}", "Thành công", "Bảo mật", ma_tk)

        # 🧩 Nếu bật 2FA → yêu cầu nhập OTP
        if twofa_enabled and totp_secret:
            session.clear()
            session["pending_2fa_user_id"] = ma_tk
            session["pending_role"] = vai_tro  # ⚙️ lưu vai trò tạm
            flash("🔐 Tài khoản có bật xác thực hai lớp. Vui lòng nhập mã OTP từ ứng dụng Google Authenticator.", "info")
            conn.close()
            return redirect(url_for("auth_bp.verify_2fa"))

        # ⚙️ Nếu chưa bật 2FA → ép người dùng bật bảo mật
        if not twofa_enabled or not totp_secret:
            session.clear()
            session["user_id"] = ma_tk
            session["username"] = ten_dang_nhap or ma_nv or email
            session["manv"] = ma_nv
            session["email"] = email
            session["hoten"] = ho_ten
            session["role"] = vai_tro
            session["roles"] = (vai_tro,)
            flash("⚙️ Vui lòng bật xác thực hai lớp (2FA) để bảo mật tài khoản của bạn.", "info")
            conn.close()
            return redirect(url_for("auth_bp.security"))

        # 🧑‍💻 Nếu chưa có khuôn mặt → yêu cầu đăng ký
        if not da_km:
            cursor.execute("SELECT COUNT(*) FROM KhuonMat WHERE MaNV = ?", (ma_nv,))
            face_count = cursor.fetchone()[0]
            if face_count > 0:
                cursor.execute("""
                    UPDATE TaiKhoan
                    SET DaDangKyKhuonMat = 1
                    WHERE MaNV = ?
                """, (ma_nv,))
                conn.commit()
                print(f"[AUTO-FIX] ✅ Đã có khuôn mặt → cập nhật DaDangKyKhuonMat = 1 cho {ma_nv}")
            else:
                flash("🧑‍💻 Tài khoản đã xác thực. Vui lòng đăng ký khuôn mặt để hoàn tất.", "info")
                conn.close()
                return redirect(url_for("register_bp.register"))

        # 💾 Lưu session đầy đủ (khi không bật 2FA)
        session.clear()
        session["user_id"] = ma_tk
        session["username"] = ten_dang_nhap or ma_nv or email
        session["role"] = vai_tro
        session["roles"] = (vai_tro,)
        session["manv"] = ma_nv
        session["hoten"] = ho_ten
        session["email"] = email

        conn.close()

        # ✅ Điều hướng theo vai trò
        if vai_tro == "admin":
            flash("👑 Chào mừng Admin quay lại!", "success")
            return redirect(url_for("admin_dashboard"))
        elif vai_tro == "hr":
            flash("📋 Chào mừng Nhân sự!", "success")
            return redirect(url_for("dashboard_bp.hr_dashboard")
)
        elif vai_tro in ("quanlyphongban", "qlpb"):
            flash("🏢 Chào mừng Quản lý phòng ban!", "success")
            return redirect(url_for("qlpb_bp.qlpb_dashboard"))
        elif vai_tro == "nhanvien":
            flash("✅ Đăng nhập thành công!", "success")
            return redirect(url_for("employee_bp.employee_dashboard"))
        else:
            flash("⚠️ Vai trò không hợp lệ hoặc chưa được gán!", "warning")
            return redirect(url_for("auth_bp.login"))

    # Nếu GET
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
