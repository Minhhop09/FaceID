from flask import Blueprint, redirect, url_for, flash, current_app
from datetime import datetime
from threading import Thread
from core.db_utils import get_sql_connection
from core.decorators import require_role
from core.attendance_utils import cap_nhat_vang_va_phep
from core.email_utils import send_email_notification

update_absences_bp = Blueprint("update_absences_bp", __name__)

@update_absences_bp.route("/update_absences", methods=["POST"])
@require_role("admin", "hr")
def update_absences():
    """
    ✅ Cập nhật trạng thái vắng và gửi email nhắc nhở cho nhân viên vắng mặt.
    - Cập nhật trạng thái vắng trong LichLamViec / ChamCong
    - Gửi mail song song trong thread riêng (có app_context)
    - Ghi lại lịch sử gửi mail trong bảng LichSuEmail
    """
    conn = get_sql_connection()
    cursor = conn.cursor()
    sent_count = 0  # ✅ KHỞI TẠO BIẾN TRƯỚC

    try:
        # 1️⃣ Cập nhật trạng thái vắng
        cap_nhat_vang_va_phep()
        print("✅ Đã cập nhật trạng thái vắng trong bảng LichLamViec / ChamCong.")

        # 2️⃣ Lấy danh sách nhân viên vắng hôm nay
        cursor.execute("""
            SELECT NV.MaNV, NV.HoTen, NV.Email, PB.TenPB, CLV.TenCa,
                   CLV.GioBatDau, CLV.GioKetThuc, CC.NgayChamCong
            FROM ChamCong CC
            JOIN NhanVien NV ON CC.MaNV = NV.MaNV
            JOIN PhongBan PB ON NV.MaPB = PB.MaPB
            JOIN CaLamViec CLV ON CC.MaCa = CLV.MaCa
            WHERE CONVERT(DATE, CC.NgayChamCong) = CONVERT(DATE, GETDATE())
              AND CC.TrangThai = 0              -- 0 = Vắng
              AND NV.TrangThai = 1              -- Nhân viên đang hoạt động
              AND NV.Email IS NOT NULL
              AND NV.Email <> ''
              AND (CC.DaXoa = 0 OR CC.DaXoa = 1);
        """)
        absents = cursor.fetchall()

        if not absents:
            flash("🎉 Không có nhân viên nào vắng hôm nay!", "info")
            return redirect(url_for("attendance_bp.attendance_report"))

        app = current_app._get_current_object()  # ✅ Lấy app để dùng trong thread

        # 3️⃣ Hàm gửi email (chạy trong thread)
        def send_absent_email(app, ma_nv, hoten, email, ten_pb, ten_ca, gio_bd, gio_kt, ngay_lam):
            """Gửi email cho 1 nhân viên và ghi lịch sử"""
            with app.app_context():
                local_conn = get_sql_connection()
                local_cursor = local_conn.cursor()
                try:
                    ngay_str = (
                        ngay_lam.strftime("%d/%m/%Y")
                        if hasattr(ngay_lam, "strftime")
                        else str(ngay_lam)
                    )

                    # 📨 Soạn nội dung mail
                    subject = f"📩 Thông báo vắng mặt - Ca {ten_ca} ngày {ngay_str}"
                    body = (
                        f"Kính gửi {hoten},\n\n"
                        f"Hệ thống FaceID ghi nhận bạn đã **vắng mặt** trong ca làm việc **{ten_ca}** ngày **{ngay_str}**.\n"
                        f"👉 Thời gian ca: {gio_bd} - {gio_kt}\n"
                        f"📍 Phòng ban: {ten_pb}\n\n"
                        f"Nếu có lý do chính đáng, vui lòng phản hồi lại bộ phận nhân sự.\n\n"
                        f"Trân trọng,\nHệ thống FaceID"
                    )

                    # 🧭 Gửi email
                    status = "Thành công" if send_email_notification(email, subject, body) else "Thất bại"
                    print(f"📬 Gửi mail {status} đến {hoten} ({email})")

                    # 🧾 Ghi lịch sử gửi mail
                    local_cursor.execute("""
                        INSERT INTO LichSuEmail (MaTK, EmailTo, LoaiThongBao, ThoiGian, TrangThai)
                        SELECT TK.MaTK, NV.Email, N'Nhắc nhở vắng mặt', GETDATE(), ?
                        FROM TaiKhoan TK JOIN NhanVien NV ON TK.MaNV = NV.MaNV
                        WHERE NV.MaNV = ?;
                    """, (status, ma_nv))
                    local_conn.commit()

                except Exception as e:
                    print(f"❌ Lỗi khi gửi mail cho {email}: {e}")
                finally:
                    local_conn.close()

        # 4️⃣ Tạo thread gửi mail song song
        for nv in absents:
            Thread(target=send_absent_email, args=(app, *nv), daemon=True).start()
            sent_count += 1

        flash(f"✅ Đã kích hoạt gửi {sent_count} email nhắc nhở vắng mặt trong nền!", "success")
        print(f"💌 Đang gửi {sent_count} email nhắc nhở trong nền...")

        conn.commit()
        return redirect(url_for("attendance_bp.attendance_report"))

    except Exception as e:
        print(f"❌ Lỗi xảy ra khi cập nhật hoặc gửi mail: {e}")
        try:
            conn.rollback()
        except Exception as err:
            print(f"⚠️ Không thể rollback: {err}")

        flash(f"❌ Lỗi khi cập nhật hoặc gửi mail: {e}", "danger")
        return redirect(url_for("attendance_bp.attendance_report"))

    finally:
        try:
            conn.close()
        except Exception as err:
            print(f"⚠️ Lỗi khi đóng connection: {err}")
