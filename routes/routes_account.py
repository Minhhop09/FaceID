# ===============================================
# 🧩 routes_account.py — Xử lý tài khoản & email
# ===============================================
from flask import Blueprint, flash, redirect, url_for
from core.db_utils import get_sql_connection
from core.decorators import require_role
from core.email_utils import send_email_notification  # hàm gửi mail hiện tại

account_bp = Blueprint("account_bp", __name__)

@account_bp.route("/update_account_status/<ma_tk>/<int:trang_thai>", methods=["POST"])
@require_role("admin")
def update_account_status(ma_tk, trang_thai):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # 1️⃣ Cập nhật trạng thái tài khoản
        cursor.execute("UPDATE TaiKhoan SET TrangThai = ? WHERE MaTK = ?", (trang_thai, ma_tk))
        conn.commit()

        # 2️⃣ Lấy email và họ tên nhân viên
        cursor.execute("""
            SELECT NV.Email, NV.HoTen, TK.MaTK
            FROM TaiKhoan TK
            JOIN NhanVien NV ON TK.MaNV = NV.MaNV
            WHERE TK.MaTK = ?
        """, (ma_tk,))
        row = cursor.fetchone()

        if row:
            email, hoten, ma_tk_int = row

            # 3️⃣ Chuẩn bị nội dung mail
            if trang_thai == 0:
                subject = "🔒 Tài khoản của bạn đã bị khóa"
                body = (
                    f"Xin chào {hoten},\n\n"
                    "Tài khoản của bạn đã bị khóa bởi quản trị viên.\n"
                    "Vui lòng liên hệ phòng nhân sự nếu cần hỗ trợ."
                )
                loai_tb = "Khóa tài khoản"
            else:
                subject = "🔓 Tài khoản của bạn đã được mở lại"
                body = (
                    f"Xin chào {hoten},\n\n"
                    "Tài khoản của bạn đã được kích hoạt trở lại.\n"
                    "Bạn có thể đăng nhập vào hệ thống."
                )
                loai_tb = "Mở khóa tài khoản"

            # 4️⃣ Gửi mail + ghi log
            trang_thai_gui = "Thành công"
            try:
                send_email_notification(email, subject, body)
                print(f"✅ Email đã gửi đến {email} — {loai_tb}")
            except Exception as e:
                trang_thai_gui = f"Lỗi: {str(e)}"
                print(f"❌ Lỗi khi gửi mail cho {email}: {e}")

            # 5️⃣ Ghi lịch sử vào bảng LichSuEmail (dạng INT)
            cursor.execute("""
                INSERT INTO LichSuEmail (MaTK, EmailTo, LoaiThongBao, ThoiGian, TrangThai)
                VALUES (?, ?, ?, GETDATE(), ?)
            """, (ma_tk_int, email or "", loai_tb, trang_thai_gui))
            conn.commit()

        flash("✅ Đã cập nhật trạng thái tài khoản và ghi lịch sử email!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi cập nhật trạng thái: {e}", "danger")

    finally:
        conn.close()

    return redirect(url_for("account_list"))
