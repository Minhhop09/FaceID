# ==============================================================
# 📧 auto_notify_shift_end.py — Gửi email nhắc nhở khi cập nhật vắng
# ==============================================================

import pyodbc
from datetime import datetime
from flask import current_app
from flask_mail import Message
from core.db_utils import get_sql_connection
from core.config_mail import mail

def send_mail_remind_unchecked_shift(app=None):
    """
    Gửi email nhắc nhở cho nhân viên bị đánh dấu vắng trong ngày hiện tại.
   Chạy sau khi admin bấm 'Cập nhật vắng'.
    - Lấy tất cả nhân viên có LLV.TrangThai = 2 và chưa có chấm công hôm nay.
    - Gửi email thông báo vắng mặt đến từng người.
    - Lưu log gửi mail ra console và (tùy chọn) bảng lịch sử.
    """
    now = datetime.now()
    time_str = now.strftime("%H:%M:%S")
    date_str = now.strftime("%d/%m/%Y")
    print(f"\n[{time_str}] Bắt đầu gửi email nhắc nhở vắng mặt...")

    conn = get_sql_connection()
    cursor = conn.cursor()

    # Truy vấn tất cả nhân viên bị đánh dấu vắng hôm nay
    cursor.execute("""
        SELECT NV.HoTen, NV.Email, PB.TenPB, CLV.TenCa, CLV.GioBatDau, CLV.GioKetThuc
        FROM LichLamViec LLV
        JOIN NhanVien NV ON LLV.MaNV = NV.MaNV
        JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        JOIN CaLamViec CLV ON LLV.MaCa = CLV.MaCa
        LEFT JOIN ChamCong CC
            ON CC.MaNV = LLV.MaNV
           AND CC.MaCa = LLV.MaCa
           AND CC.NgayChamCong = LLV.NgayLam
        WHERE LLV.NgayLam = CAST(GETDATE() AS DATE)
          AND LLV.TrangThai = 2            -- 2 = Vắng
          AND NV.TrangThai = 1             -- Nhân viên đang hoạt động
          AND NV.Email IS NOT NULL
          AND LLV.DaXoa = 1
          AND CC.MaChamCong IS NULL        -- Chưa chấm công
    """)

    rows = cursor.fetchall()
    total_sent = 0

    if not rows:
        print(f"[{time_str}] Không có nhân viên nào cần gửi email hôm nay.")
        conn.close()
        return 0

    # Dùng app context nếu cần
    context = (app or current_app).app_context()
    with context:
        for ho_ten, email, ten_pb, ten_ca, gio_bat_dau, gio_ket_thuc in rows:
            subject = f"Thông báo vắng mặt - Ca {ten_ca}"
            body = f"""
Xin chào {ho_ten},

Hệ thống FaceID ghi nhận bạn **vắng mặt** trong ca {ten_ca} hôm nay ({date_str}).

Thời gian ca: {gio_bat_dau} - {gio_ket_thuc}
Phòng ban: {ten_pb}

Nếu có lý do chính đáng (ví dụ: xin nghỉ phép, lỗi hệ thống, quên chấm công),
vui lòng phản hồi với bộ phận nhân sự để được xử lý.

Trân trọng,
Hệ thống FaceID
"""

            try:
                msg = Message(
                    subject=subject,
                    recipients=[email],
                    body=body,
                    sender=current_app.config.get("MAIL_DEFAULT_SENDER", current_app.config["MAIL_USERNAME"])
                )
                mail.send(msg)
                total_sent += 1
                print(f"Đã gửi mail đến {ho_ten} ({email})")
            except Exception as e:
                print(f"Lỗi gửi mail đến {email}: {e}")

    # (Tùy chọn) Ghi log lịch sử vào DB
    try:
        cursor.execute("""
            INSERT INTO LichSuThayDoi (TenBang, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES (N'Hệ thống gửi mail', N'Gửi email nhắc nhở vắng mặt', N'Tổng số mail', '', ?, GETDATE(), N'Hệ thống')
        """, (str(total_sent),))
        conn.commit()
    except Exception:
        pass  # không cần dừng hệ thống nếu không ghi log được

    conn.close()
    print(f"Hoàn tất gửi email — Tổng số: {total_sent} nhân viên.\n")
    return total_sent
