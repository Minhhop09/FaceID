# routes/qlpb_bp.py
from flask import Blueprint, render_template, session, flash, redirect, url_for
from core.db_utils import get_sql_connection
from core.decorators import require_role

qlpb_bp = Blueprint("qlpb_bp", __name__)

# ============================================================
# 🧭 DASHBOARD - QUẢN LÝ PHÒNG BAN
# ============================================================
@qlpb_bp.route("/qlpb_dashboard")
@require_role("quanlyphongban")
def qlpb_dashboard():
    conn = get_sql_connection()
    cursor = conn.cursor()

    username = session.get("username")

    # 🔹 Lấy mã phòng ban và tên phòng ban của người quản lý
    cursor.execute("""
        SELECT nv.MaPB, pb.TenPB
        FROM NhanVien nv
        JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        JOIN TaiKhoan tk ON nv.MaNV = tk.MaNV
        WHERE tk.TenDangNhap = ?
    """, (username,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("❌ Không tìm thấy thông tin phòng ban!", "danger")
        return redirect(url_for("login"))

    ma_pb, ten_pb = row

    # 🔹 Đếm số nhân viên trong phòng
    cursor.execute("""
        SELECT COUNT(*) 
        FROM NhanVien 
        WHERE MaPB = ? AND TrangThai = 1
    """, (ma_pb,))
    total_employees_in_department = cursor.fetchone()[0]

    # 🔹 Đếm số ca làm việc của nhân viên trong phòng
    cursor.execute("""
        SELECT COUNT(DISTINCT clv.MaCa)
        FROM LichLamViec llv
        JOIN NhanVien nv ON llv.MaNV = nv.MaNV
        JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
        WHERE nv.MaPB = ? AND llv.DaXoa = 1
    """, (ma_pb,))
    total_shifts = cursor.fetchone()[0]

    # 🔹 Đếm số tài khoản QLPB đang hoạt động
    cursor.execute("""
        SELECT COUNT(*)
        FROM TaiKhoan tk
        JOIN NhanVien nv ON tk.MaNV = nv.MaNV
        WHERE nv.MaPB = ? AND tk.VaiTro = 'quanlyphongban' AND tk.TrangThai = 1
    """, (ma_pb,))
    total_accounts = cursor.fetchone()[0]

    # 🔹 Trạng thái hoạt động của phòng ban
    cursor.execute("SELECT TrangThai FROM PhongBan WHERE MaPB = ?", (ma_pb,))
    pb_status = cursor.fetchone()[0]

    conn.close()

    return render_template(
        "qlpb_dashboard.html",
        phongban=ten_pb,
        total_employees_in_department=total_employees_in_department,
        total_shifts=total_shifts,
        total_accounts=total_accounts,
        pb_status=pb_status
    )
