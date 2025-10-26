from flask import Blueprint, render_template, request
from core.db_utils import get_sql_connection
from datetime import datetime
from core.decorators import require_role

# ===========================================
# 📊 Blueprint Dashboard tổng hợp
# ===========================================
dashboard_bp = Blueprint("dashboard_bp", __name__)

# ============================================================
# 1️⃣ DASHBOARD LƯƠNG (phân tích trung bình theo phòng ban)
# ============================================================
@dashboard_bp.route("/salary_dashboard")
@require_role("hr", "admin")
def salary_dashboard():
    """Hiển thị thống kê lương trung bình theo phòng ban"""
    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🗓 Lọc theo tháng/năm
    month = int(request.args.get("month", datetime.now().month))
    year = int(request.args.get("year", datetime.now().year))

    # 🟢 Lương trung bình theo phòng ban
    cursor.execute("""
        SELECT PB.TenPB, AVG(L.TongLuong) AS AvgSalary
        FROM Luong L
        JOIN NhanVien NV ON L.MaNV = NV.MaNV
        JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        WHERE MONTH(L.ThangNam)=? AND YEAR(L.ThangNam)=? AND L.DaXoa=1
        GROUP BY PB.TenPB
    """, (month, year))
    salary_data = cursor.fetchall()
    departments = [r[0] for r in salary_data]
    avg_salaries = [float(r[1]) for r in salary_data]

    # 🟢 Tỷ lệ chấm công
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN TrangThai=1 THEN 1 ELSE 0 END) AS DiDungGio,
            SUM(CASE WHEN TrangThai=2 THEN 1 ELSE 0 END) AS DiMuon,
            SUM(CASE WHEN TrangThai=0 THEN 1 ELSE 0 END) AS Vang
        FROM ChamCong
        WHERE MONTH(NgayChamCong)=? AND YEAR(NgayChamCong)=?
    """, (month, year))
    stats = cursor.fetchone()
    conn.close()

    return render_template(
        "salary_dashboard.html",
        departments=departments,
        avg_salaries=avg_salaries,
        stats=stats,
        month=month,
        year=year
    )


# ============================================================
# 2️⃣ DASHBOARD NHÂN SỰ (HR / ADMIN)
# ============================================================
@dashboard_bp.route("/hr_dashboard")
@require_role("hr", "admin")
def hr_dashboard():
    """Hiển thị tổng quan nhân sự (số nhân viên, ca làm, khuôn mặt...)"""
    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🔹 Khởi tạo sẵn để tránh lỗi Undefined
    total_employees = total_shifts = total_faces = 0
    departments = []
    avg_salaries = []
    stats = [0, 0, 0]  # [đi đúng giờ, đi muộn, vắng]

    try:
        # 1️⃣ Tổng nhân viên đang hoạt động
        cursor.execute("SELECT COUNT(*) FROM NhanVien WHERE TrangThai = 1")
        total_employees = cursor.fetchone()[0] or 0

        # 2️⃣ Tổng ca làm việc đang hoạt động
        cursor.execute("SELECT COUNT(*) FROM CaLamViec WHERE TrangThai = 1")
        total_shifts = cursor.fetchone()[0] or 0

        # 3️⃣ Số nhân viên đã đăng ký khuôn mặt
        cursor.execute("SELECT COUNT(*) FROM KhuonMat WHERE TrangThai = 1")
        total_faces = cursor.fetchone()[0] or 0

        # 4️⃣ Biểu đồ: Lương trung bình theo phòng ban
        cursor.execute("""
            SELECT PB.TenPB, AVG(L.TongLuong) AS LuongTB
            FROM Luong L
            JOIN NhanVien NV ON L.MaNV = NV.MaNV
            JOIN PhongBan PB ON NV.MaPB = PB.MaPB
            WHERE PB.TrangThai = 1 AND NV.TrangThai = 1
            GROUP BY PB.TenPB
        """)
        rows = cursor.fetchall()
        departments = [r[0] for r in rows]
        avg_salaries = [float(r[1]) if r[1] else 0 for r in rows]

        # 5️⃣ Biểu đồ: Thống kê chấm công
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN TrangThai = 1 THEN 1 ELSE 0 END) AS DungGio,
                SUM(CASE WHEN TrangThai = 2 THEN 1 ELSE 0 END) AS DiMuon,
                SUM(CASE WHEN TrangThai = 3 THEN 1 ELSE 0 END) AS Vang
            FROM ChamCong
            WHERE CONVERT(DATE, NgayChamCong) >= DATEADD(DAY, -30, GETDATE())
        """)
        row = cursor.fetchone()
        if row:
            stats = [row[0] or 0, row[1] or 0, row[2] or 0]

    except Exception as e:
        print("❌ Lỗi khi tải dashboard HR:", e)
    finally:
        conn.close()

    return render_template(
        "hr_dashboard.html",
        total_employees=total_employees,
        total_shifts=total_shifts,
        total_faces=total_faces,
        departments=departments,
        avg_salaries=avg_salaries,
        stats=stats
    )
