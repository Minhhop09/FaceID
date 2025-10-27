from flask_mail import Mail, Message
from flask import current_app, session
from core.db_utils import get_sql_connection
from datetime import datetime
import smtplib
from email.message import EmailMessage
import os


# ============================================================
# 📬 Gửi email thông báo + Ghi log vào LichSuEmail
# ============================================================
def send_email_notification(email_to, subject, body, loai="GENERAL", ma_tham_chieu=None, ma_tk=None):
    """
    Gửi email qua Flask-Mail (thật) và ghi log vào LichSuEmail.
    ------------------------------------------------------------
    Parameters:
        email_to (str | list): người nhận email
        subject (str): tiêu đề email
        body (str): nội dung email
        loai (str): loại thông báo (OTP, PAYMENT_RECEIPT, ALERT, ...)
        ma_tham_chieu (str | None): mã nghiệp vụ (MaLuong, MaNV, RESET_PASSWORD, ...)
        ma_tk (int | None): ID tài khoản trong bảng TaiKhoan (FK)
    ------------------------------------------------------------
    """
    success = False
    try:
        # 🟢 Lấy app context thực để Flask-Mail hoạt động an toàn
        app = current_app._get_current_object()
        with app.app_context():
            mail = Mail(app)

            # Cho phép gửi 1 hoặc nhiều người nhận
            recipients = [email_to] if isinstance(email_to, str) else list(email_to)

            msg = Message(
                subject=subject,
                sender=app.config.get("MAIL_USERNAME"),
                recipients=recipients,
                body=body
            )

            # Gửi mail thật
            mail.send(msg)
            success = True
            print(f"✅ Email đã gửi đến {', '.join(recipients)} — {subject}")

    except Exception as e:
        # Nếu lỗi gửi email
        print(f"❌ Lỗi gửi email đến {email_to}: {e}")
        success = False

    # ============================================================
    # 🧾 Ghi log email vào LichSuEmail
    # ============================================================
    try:
        conn = get_sql_connection()
        cur = conn.cursor()

        # 🧱 Ghi log kết quả gửi
        cur.execute("""
            INSERT INTO LichSuEmail (MaTK, MaThamChieu, EmailTo, LoaiThongBao, ThoiGian, TrangThai)
            VALUES (?, ?, ?, ?, GETDATE(), ?)
        """, (
            ma_tk,  # ID tài khoản (INT)
            ma_tham_chieu or "N/A",  # mã nghiệp vụ
            email_to if isinstance(email_to, str) else ", ".join(email_to),
            loai,
            1 if success else 0
        ))

        conn.commit()
        print(f"[LOG] 📧 Đã ghi log email {loai} → {email_to}")

    except Exception as log_err:
        print(f"[WARN] ⚠️ Không thể ghi log email: {log_err}")

    finally:
        if 'conn' in locals():
            conn.close()

    return success

def notify_attendance(ma_nv: str, trang_thai: str, gio_vao: datetime):
    """
    Gửi email thông báo chấm công cho nhân viên.
    ------------------------------------------------------------
    ma_nv       : mã nhân viên (NV00001, ...)
    trang_thai  : "Đúng giờ", "Đi trễ", "Vắng", ...
    gio_vao     : thời gian chấm công thực tế
    ------------------------------------------------------------
    """

    try:
        conn = get_sql_connection()
        cur = conn.cursor()

        # 🔍 Lấy thông tin nhân viên
        cur.execute("SELECT HoTen, Email FROM NhanVien WHERE MaNV = ?", (ma_nv,))
        row = cur.fetchone()
        if not row:
            print(f"[WARN] ⚠️ Không tìm thấy nhân viên {ma_nv} để gửi mail chấm công.")
            return False

        ho_ten, email_to = row
        ngay_cc = gio_vao.strftime("%d/%m/%Y")
        gio_cc = gio_vao.strftime("%H:%M:%S")

        # 🧾 Soạn nội dung email
        if trang_thai.lower() == "đúng giờ":
            subject = f"[FaceID] Chấm công thành công ngày {ngay_cc}"
            body = f"""
Xin chào {ho_ten},

Bạn đã chấm công thành công vào lúc {gio_cc} ngày {ngay_cc}.

✅ Trạng thái: Đúng giờ
Cảm ơn bạn đã tuân thủ giờ làm việc!

Trân trọng,
Hệ thống FaceID
"""
        else:
            subject = f"[FaceID] Thông báo đi trễ ngày {ngay_cc}"
            body = f"""
Xin chào {ho_ten},

Bạn đã chấm công vào lúc {gio_cc} ngày {ngay_cc}.

⚠️ Trạng thái: {trang_thai}
Vui lòng chú ý giờ làm việc đúng quy định của công ty.

Trân trọng,
Hệ thống FaceID
"""

        # 📬 Gửi và ghi log
        return send_email_notification(
            email_to=email_to,
            subject=subject,
            body=body,
            loai="ATTENDANCE",
            ma_tham_chieu=ma_nv,
            ma_tk=None
        )

    except Exception as e:
        print(f"[ERROR] ❌ Lỗi khi gửi email chấm công: {e}")
        return False

    finally:
        if 'conn' in locals():
            conn.close()
            
# ============================================================
# 🔐 Gửi OTP đặt lại mật khẩu
# ============================================================
def send_otp_email(email_to, otp, ma_tk=None):
    """
    Gửi mã OTP đặt lại mật khẩu và ghi log email.
    """
    subject = "🔐 Mã xác minh đặt lại mật khẩu FaceID"
    body = (
        f"Kính gửi người dùng,\n\n"
        f"Mã xác minh (OTP) của bạn là: {otp}\n\n"
        f"Mã này có hiệu lực trong 5 phút.\n"
        f"Vui lòng không chia sẻ mã này cho bất kỳ ai.\n\n"
        f"Trân trọng,\nHệ thống FaceID"
    )

    return send_email_notification(
        email_to=email_to,
        subject=subject,
        body=body,
        loai="OTP",
        ma_tham_chieu="RESET_PASSWORD",
        ma_tk=ma_tk
    )

def send_email_with_attachment(to_email, subject, body, attachment_path=None):
    app = current_app._get_current_object()
    mail = Mail(app)

    msg = Message(subject=subject,
                  recipients=[to_email],
                  sender=app.config.get("MAIL_USERNAME"),
                  body=body)

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            msg.attach(os.path.basename(attachment_path),
                       "application/pdf",
                       f.read())

    try:
        mail.send(msg)
        print(f"[EMAIL OK] ✅ Đã gửi thật tới {to_email}")
        return True, None
    except Exception as e:
        print(f"[EMAIL ERROR] ❌ Không gửi được email: {e}")
        print(f"[EMAIL FALLBACK] 🧪 Giả lập gửi email tới {to_email}")
        if attachment_path:
            print(f"   (Giả lập) Đính kèm: {os.path.basename(attachment_path)}")
        return True, "Sent in fake/demo mode"