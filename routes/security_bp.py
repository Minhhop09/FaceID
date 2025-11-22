# routes/security_bp.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file
import pyotp, qrcode, io
from core.db_utils import get_sql_connection
from core.decorators import require_role  # hoặc tự viết require_login nếu bạn muốn
from core.log_utils import log_action

security_bp = Blueprint("security_bp", __name__, url_prefix="/security")

def _get_user_record(matk: int):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MaTK, TenDangNhap, Email, TOTP_Secret, TwoFA_Enabled
        FROM TaiKhoan WHERE MaTK = ?
    """, (matk,))
    row = cursor.fetchone()
    conn.close()
    return row

@security_bp.route("/settings")
@require_role("admin", "hr", "quanlyphongban", "nhanvien")  # hoặc 1 decorator require_login tuỳ hệ thống
def settings():
    if "user_id" not in session:
        return redirect(url_for("auth_bp.login"))
    matk = session["user_id"]
    user = _get_user_record(matk)
    return render_template("security.html", user=user)

@security_bp.route("/generate_qr")
@require_role("admin", "hr", "quanlyphongban", "nhanvien")
def generate_qr():
    # Chỉ hiển thị QR **tạm** (chưa bật 2FA) để người dùng quét và xác nhận OTP lần đầu.
    if "user_id" not in session:
        return redirect(url_for("auth_bp.login"))
    matk = session["user_id"]

    # Lấy email để hiển thị trong Authenticator
    conn = get_sql_connection()
    cursor = conn.cursor()

    # Nếu đã có secret → dùng lại; nếu chưa → tạo mới và lưu tạm
    cursor.execute("SELECT Email, TOTP_Secret, TwoFA_Enabled FROM TaiKhoan WHERE MaTK = ?", (matk,))
    email, secret, enabled = cursor.fetchone()

    if not secret:
        # Sinh secret mới và lưu (chưa bật TwoFA_Enabled)
        secret = pyotp.random_base32()
        cursor.execute("UPDATE TaiKhoan SET TOTP_Secret = ? WHERE MaTK = ?", (secret, matk))
        conn.commit()

    conn.close()

    issuer = "FaceID System"
    otp_uri = pyotp.TOTP(secret).provisioning_uri(name=email or f"user-{matk}", issuer_name=issuer)

    img = qrcode.make(otp_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@security_bp.route("/enable_2fa", methods=["POST"])
@require_role("admin", "hr", "quanlyphongban", "nhanvien")
def enable_2fa():
    if "user_id" not in session:
        return redirect(url_for("auth_bp.login"))
    matk = session["user_id"]
    otp = (request.form.get("otp") or request.json.get("otp") if request.is_json else "").strip()

    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TOTP_Secret FROM TaiKhoan WHERE MaTK = ?", (matk,))
    row = cursor.fetchone()
    if not row or not row[0]:
        conn.close()
        flash("Không tìm thấy secret. Vui lòng tải lại QR và thử lại.", "danger")
        log_action("ENABLE_2FA", "Secret missing", "Thất bại", matk)
        return redirect(url_for("security_bp.settings"))

    secret = row[0]
    totp = pyotp.TOTP(secret)
    if not otp or not totp.verify(otp):
        conn.close()
        flash("Mã OTP không đúng hoặc đã hết hạn.", "danger")
        log_action("ENABLE_2FA", "OTP invalid", "Thất bại", matk)
        return redirect(url_for("security_bp.settings"))

    cursor.execute("UPDATE TaiKhoan SET TwoFA_Enabled = 1 WHERE MaTK = ?", (matk,))
    conn.commit()
    conn.close()

    log_action("ENABLE_2FA", "User enabled 2FA", "Thành công", matk)
    flash("Đã bật xác thực hai bước (2FA).", "success")
    return redirect(url_for("security_bp.settings"))

@security_bp.route("/disable_2fa", methods=["POST"])
@require_role("admin", "hr", "quanlyphongban", "nhanvien")
def disable_2fa():
    if "user_id" not in session:
        return redirect(url_for("auth_bp.login"))
    matk = session["user_id"]
    # Bạn có thể yêu cầu nhập OTP hiện tại để tắt (khuyến nghị). Ở đây cho phép tắt trực tiếp:
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE TaiKhoan SET TwoFA_Enabled = 0 WHERE MaTK = ?", (matk,))
    conn.commit()
    conn.close()

    log_action("DISABLE_2FA", "User disabled 2FA", "Thành công", matk)
    flash("Đã tắt xác thực hai bước (2FA).", "warning")
    return redirect(url_for("security_bp.settings"))
