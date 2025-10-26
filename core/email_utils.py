# ===============================================
# 📧 core/email_utils.py — Gửi email hệ thống
# ===============================================

from flask_mail import Mail, Message
from flask import current_app

def send_email_notification(email_to, subject, body):
    """
    ✅ Gửi email thông báo an toàn (hỗ trợ thread).
    - Tự động tạo app_context nếu cần.
    - Hỗ trợ 1 hoặc nhiều người nhận.
    - Trả về True nếu gửi thành công, False nếu lỗi.
    """
    try:
        app = current_app._get_current_object()  # Lấy app thật (tránh proxy lỗi khi thread chạy)
        with app.app_context():                  # Đảm bảo luôn có context hợp lệ
            mail = Mail(app)

            # Cho phép gửi 1 hoặc nhiều người nhận
            recipients = [email_to] if isinstance(email_to, str) else list(email_to)

            msg = Message(
                subject=subject,
                sender=app.config.get("MAIL_USERNAME"),
                recipients=recipients,
                body=body
            )

            mail.send(msg)
            print(f"✅ Email đã gửi đến {', '.join(recipients)} — {subject}")
            return True

    except Exception as e:
        print(f"❌ Lỗi gửi email đến {email_to}: {e}")
        return False


def send_otp_email(email_to, otp):
    """
    ✅ Gửi mã OTP đặt lại mật khẩu.
    - Gọi lại send_email_notification để tránh trùng code.
    """
    subject = "🔐 Mã xác minh đặt lại mật khẩu FaceID"
    body = (
        f"Kính gửi người dùng,\n\n"
        f"Mã xác minh (OTP) của bạn là: {otp}\n\n"
        f"Mã này có hiệu lực trong 5 phút.\n"
        f"Vui lòng không chia sẻ mã này cho bất kỳ ai.\n\n"
        f"Trân trọng,\nHệ thống FaceID"
    )
    return send_email_notification(email_to, subject, body)
