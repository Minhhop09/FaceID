import pyodbc
from datetime import datetime

# ⚙️ Cấu hình máy chủ & CSDL
SERVER_NAME = "MINHHOP\\SQLEXPRESS"
DB_NAME = "FaceID"

# ============================================================
# 🔹 Hàm kết nối chính — Dùng cho tất cả module
# ============================================================
def get_sql_connection():
    """
    Mở kết nối tới SQL Server (dùng driver mới ODBC Driver 17).
    Fix lỗi 'HYC00 SQLBindParameter' và hỗ trợ Unicode, parameter binding.
    """
    try:
        conn = pyodbc.connect(
            "DRIVER={ODBC Driver 17 for SQL Server};"  # ✅ driver mới
            f"SERVER={SERVER_NAME};"
            f"DATABASE={DB_NAME};"
            "Trusted_Connection=yes;"                   # đăng nhập Windows user
            "TrustServerCertificate=yes;"               # tránh lỗi SSL nội bộ
        )
        cursor = conn.cursor()
        cursor.execute("SELECT DB_NAME(), SUSER_NAME()")
        db, user = cursor.fetchone()
        return conn
    except Exception as e:
        print(f"❌ Lỗi kết nối CSDL: {e}")
        return None
    
def get_connection():
    try:
        conn_str = (
            "Driver={SQL Server};"
            "Server=MINHHOP\\SQLEXPRESS;"
            "Database=FaceID;"
            "Trusted_Connection=yes;"
        )
        return pyodbc.connect(conn_str)
    except Exception as e:
        print(f"Lỗi kết nối CSDL: {e}")
        return None

# ============================================================
# 🔹 Một số hàm tiện ích có thể dùng lại
# ============================================================

def find_employees_by_name_or_manv(keyword):
    conn = get_sql_connection()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM NhanVien WHERE MaNV = ? OR HoTen LIKE ?",
        (keyword, f"%{keyword}%")
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_phongbans():
    conn = get_sql_connection()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("SELECT MaPB, TenPB FROM PhongBan")
    rows = cursor.fetchall()
    conn.close()
    return [{"MaPB": r.MaPB, "TenPB": r.TenPB} for r in rows]


def record_attendance(ma_nv):
    conn = get_sql_connection()
    if not conn:
        return
    cursor = conn.cursor()

    today = datetime.now().date()
    now_time = datetime.now()

    # Kiểm tra xem NV đã chấm công hôm nay chưa
    cursor.execute("""
        SELECT MaChamCong, GioVao, GioRa, TrangThai 
        FROM ChamCong 
        WHERE MaNV = ? AND NgayChamCong = ?
    """, (ma_nv, today))
    row = cursor.fetchone()

    if not row:
        # Nếu chưa có thì ghi giờ vào
        cursor.execute("""
            INSERT INTO ChamCong (MaNV, MaLLV, NgayChamCong, GioVao, TrangThai)
            VALUES (?, NULL, ?, ?, 0)
        """, (ma_nv, today, now_time))
    else:
        # Nếu đã có GioVao nhưng chưa có GioRa thì cập nhật GioRa
        if row.GioRa is None or (hasattr(row.GioRa, "year") and row.GioRa.year == 1900):
            cursor.execute("""
                UPDATE ChamCong 
                SET GioRa = ?, TrangThai = 1
                WHERE MaChamCong = ?
            """, (now_time, row.MaChamCong))
        else:
            # Nếu đã có GioVao và GioRa -> ghi thêm bản mới (ca tiếp theo)
            cursor.execute("""
                INSERT INTO ChamCong (MaNV, MaLLV, NgayChamCong, GioVao, TrangThai)
                VALUES (?, NULL, ?, ?, 0)
            """, (ma_nv, today, now_time))
    
    conn.commit()
    conn.close()
