# ============================================================
# 📧 EMAIL UTILS — FINAL FIXED V9 (OTP + ATTENDANCE + THREAD)
# ============================================================
from flask_mail import Mail, Message
from flask import current_app, session
from core.db_utils import get_sql_connection
from datetime import datetime
import os
from threading import Thread


# ============================================================
# ✅ HÀM CHÍNH: GỬI EMAIL HTML DÙNG CHUNG
# ============================================================
def send_email_notification(to_email, subject, html_body,
                            loai="GENERAL", ma_tham_chieu=None, ma_tk=None, app=None):
    """
    ✅ Hàm gửi email có nội dung HTML và ghi log vào DB.
    ------------------------------------------------------------
    • to_email: email người nhận
    • subject : tiêu đề email
    • html_body: nội dung HTML
    • loai: loại email (OTP, ATTENDANCE, ...)
    • ma_tham_chieu: mã liên quan (NV, đơn, lương,...)
    • ma_tk: ID tài khoản gửi
    • app: Flask app context
    ------------------------------------------------------------
    """
    if app is None:
        app = current_app._get_current_object()

    try:
        with app.app_context():
            mail = Mail(app)
            msg = Message(subject=subject, recipients=[to_email], html=html_body)
            mail.send(msg)
            print(f"[EMAIL] ✅ Gửi email tới {to_email} ({subject})")

            # ====== Ghi log vào bảng LichSuEmail (nếu có kết nối SQL) ======
# ====== Ghi log vào bảng LichSuEmail (nếu có kết nối SQL) ======
            try:
                conn = get_sql_connection()
                cur = conn.cursor()

                # 🔍 Nếu chưa có MaTK, tự tra bằng email
                if not ma_tk:
                    cur.execute("SELECT MaTK FROM TaiKhoan WHERE Email = ?", (to_email,))
                    row = cur.fetchone()
                    if row:
                        ma_tk = row[0]
                    else:
                        ma_tk = None  # vẫn cho phép NULL nếu chưa có trong bảng

                cur.execute("""
                    INSERT INTO LichSuEmail (MaTK, EmailTo, LoaiThongBao, ThoiGian, TrangThai, MaThamChieu)
                    VALUES (?, ?, ?, GETDATE(), N'Đã gửi', ?)
                """, (ma_tk, to_email, loai, ma_tham_chieu or subject))
                conn.commit()
                conn.close()
            except Exception as log_err:
                print(f"[EMAIL-LOG] ⚠️ Không thể ghi log: {log_err}")


            return True
    except Exception as e:
        print(f"[EMAIL] ❌ Lỗi khi gửi email tới {to_email}: {e}")
        return False


# ============================================================
# 📣 GỬI EMAIL THÔNG BÁO CHẤM CÔNG (FINAL FIXED V10)
# ============================================================
def notify_attendance(ma_nv: str, trang_thai: str, gio_vao,
                      ma_ca=None, source="auto", app=None):
    """
    Gửi email chấm công chi tiết cho nhân viên và ghi log DB.
    ------------------------------------------------------------
    - Hiển thị rõ "Đúng giờ" / "Đi muộn X phút" (nếu có trong trang_thai)
    - Thêm icon rõ ràng (✅/⚠️)
    - Gửi background thread, có ghi log vào LichSuEmail
    ------------------------------------------------------------
    """
    from datetime import datetime

    if isinstance(gio_vao, str):
        try:
            gio_vao = datetime.strptime(gio_vao, "%Y-%m-%d %H:%M:%S")
        except Exception:
            gio_vao = datetime.now()

    try:
        conn = get_sql_connection()
        cur = conn.cursor()

        # --- Lấy thông tin nhân viên và ca ---
        if ma_ca:
            cur.execute("""
                SELECT NV.HoTen, NV.Email, PB.TenPB, CLV.TenCa,
                       CONVERT(varchar(5), CLV.GioBatDau,108),
                       CONVERT(varchar(5), CLV.GioKetThuc,108)
                FROM NhanVien NV
                JOIN PhongBan PB ON NV.MaPB = PB.MaPB
                JOIN CaLamViec CLV ON CLV.MaCa = ?
                WHERE NV.MaNV = ?
            """, (ma_ca, ma_nv))
        else:
            cur.execute("""
                SELECT TOP 1 NV.HoTen, NV.Email, PB.TenPB, CLV.TenCa,
                       CONVERT(varchar(5), CLV.GioBatDau,108),
                       CONVERT(varchar(5), CLV.GioKetThuc,108)
                FROM NhanVien NV
                JOIN PhongBan PB ON NV.MaPB = PB.MaPB
                JOIN LichLamViec LLV ON LLV.MaNV = NV.MaNV
                JOIN CaLamViec CLV ON LLV.MaCa = CLV.MaCa
                WHERE NV.MaNV = ? 
                  AND CONVERT(date, LLV.NgayLam) = CONVERT(date, GETDATE())
                ORDER BY CLV.GioBatDau
            """, (ma_nv,))
        row = cur.fetchone()

        if not row:
            print(f"[WARN] ⚠️ Không tìm thấy ca cho {ma_nv} (MaCa={ma_ca})")
            return False

        ho_ten, email_to, ten_pb, ten_ca, gio_bd, gio_kt = row
        if not email_to:
            print(f"[INFO] 🚫 {ma_nv} chưa có email, bỏ qua gửi.")
            return False

        ngay_cc = gio_vao.strftime("%d/%m/%Y")
        gio_cc = gio_vao.strftime("%H:%M:%S")

        # --- Tự động chọn biểu tượng phù hợp ---
        lower_status = trang_thai.lower()
        if "đúng giờ" in lower_status:
            icon = "✅"
        elif "đi muộn" in lower_status:
            icon = "⚠️"
        elif "ra" in lower_status:
            icon = "📤"
        else:
            icon = "ℹ️"

        subject = f"[FaceID] {trang_thai} - {ngay_cc}"
        loai = f"ATTENDANCE_{source.upper()}"

        # --- Nội dung email ---
        body = f"""
        <p>Xin chào <b>{ho_ten}</b>,</p>
        <p>Hệ thống <b>FaceID</b> đã ghi nhận thông tin chấm công của bạn:</p>
        <table style="border-collapse: collapse; margin-top:8px">
            <tr><td><b>📅 Ngày:</b></td><td style="padding-left:8px">{ngay_cc}</td></tr>
            <tr><td><b>🕓 Ca làm:</b></td><td style="padding-left:8px">{ten_ca} ({gio_bd}-{gio_kt})</td></tr>
            <tr><td><b>🏢 Phòng ban:</b></td><td style="padding-left:8px">{ten_pb}</td></tr>
            <tr><td><b>🕗 Giờ ghi nhận:</b></td><td style="padding-left:8px">{gio_cc}</td></tr>
            <tr><td><b>📊 Trạng thái:</b></td><td style="padding-left:8px">{icon} {trang_thai}</td></tr>
        </table>
        <br>
        <p>Trân trọng,<br><b>Hệ thống FaceID</b></p>
        """

        # --- Gửi email ---
        if app is None:
            app = current_app._get_current_object()

        Thread(target=send_email_notification, kwargs=dict(
            to_email=email_to,
            subject=subject,
            html_body=body,
            loai=loai,
            ma_tham_chieu=ma_nv,
            ma_tk=None,
            app=app
        ), daemon=True).start()

        print(f"[EMAIL] ✉️ {icon} {trang_thai} → {ho_ten} ({email_to}) [Ca: {ten_ca}]")
        return True

    except Exception as e:
        print(f"[ERROR] ❌ notify_attendance() lỗi: {e}")
        return False
    finally:
        if 'conn' in locals():
            conn.close()

# ============================================================
# 🔐 GỬI OTP ĐẶT LẠI MẬT KHẨU
# ============================================================
def send_otp_email(email_to, otp, ma_tk=None, app=None):
    if app is None:
        app = current_app._get_current_object()

    subject = "🔐 Mã xác minh đặt lại mật khẩu FaceID"
    html_body = f"""
    <p>Xin chào,</p>
    <p>Mã xác minh (OTP) của bạn là:</p>
    <h2 style="color:#2b5797;">{otp}</h2>
    <p>Mã có hiệu lực trong 5 phút. Vui lòng không chia sẻ mã này.</p>
    <br><small>Hệ thống FaceID</small>
    """
    return send_email_notification(email_to, subject, html_body,
                                   loai="OTP", ma_tham_chieu="RESET_PASSWORD",
                                   ma_tk=ma_tk, app=app)


# ============================================================
# 📎 GỬI EMAIL CÓ ĐÍNH KÈM
# ============================================================
def send_email_with_attachment(to_email, subject, body, attachment_path=None):
    app = current_app._get_current_object()
    mail = Mail(app)
    msg = Message(subject=subject, recipients=[to_email],
                  sender=app.config.get("MAIL_USERNAME"), body=body)

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            msg.attach(os.path.basename(attachment_path),
                       "application/pdf", f.read())

    try:
        mail.send(msg)
        print(f"[EMAIL OK] ✅ Gửi thật tới {to_email}")
        return True, None
    except Exception as e:
        print(f"[EMAIL ERROR] ❌ Không gửi được email: {e}")
        print(f"[EMAIL FALLBACK] 🧪 Giả lập gửi tới {to_email}")
        if attachment_path:
            print(f"   (Giả lập) Đính kèm: {os.path.basename(attachment_path)}")
        return True, "Sent in demo mode"

def send_email_background(app, email_to, subject, html_body,
                          loai="GENERAL", ma_tham_chieu=None, ma_tk=None):
    """
    (Giữ tương thích cũ) Gửi email trong thread, đảm bảo có Flask app context.
    """
    from threading import Thread

    Thread(target=send_email_notification, kwargs=dict(
        to_email=email_to,
        subject=subject,
        html_body=html_body,
        loai=loai,
        ma_tham_chieu=ma_tham_chieu,
        ma_tk=ma_tk,
        app=app
    ), daemon=True).start()
