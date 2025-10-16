import pyodbc

SERVER_NAME = "MINHHOP\\SQLEXPRESS"
DB_NAME = "FaceID"

def get_sql_connection():
    return pyodbc.connect(
        "DRIVER={SQL Server};"
        "SERVER=MINHHOP\\SQLEXPRESS;"
        "DATABASE=FaceID;"
        "UID=sa;PWD=123456"
    )

def get_connection():
    try:
        conn_str = f"Driver={{SQL Server}};Server={SERVER_NAME};Database={DB_NAME};Trusted_Connection=yes;"
        return pyodbc.connect(conn_str)
    except Exception as e:
        print(f"❌ Lỗi kết nối CSDL: {e}")
        return None
    
def find_employees_by_name_or_manv(keyword):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM NhanVien WHERE MaNV=? OR HoTen LIKE ?", (keyword, f"%{keyword}%"))
    rows = cursor.fetchall()
    conn.close()
    return rows

def get_phongbans():
    conn = get_connection()
    if not conn:
        return []
    cursor = conn.cursor()
    cursor.execute("SELECT MaPB, TenPB FROM PhongBan")
    rows = cursor.fetchall()
    conn.close()
    return [{"MaPB": r.MaPB, "TenPB": r.TenPB} for r in rows]

def record_attendance(ma_nv):
    conn = get_connection()
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
        if row.GioRa is None or row.GioRa.year == 1900:
            cursor.execute("""
                UPDATE ChamCong 
                SET GioRa = ?, TrangThai = 1
                WHERE MaChamCong = ?
            """, (now_time, row.MaChamCong))
        else:
            # Nếu đã có GioVao và GioRa -> có thể ghi thêm bản mới (ca tiếp theo)
            cursor.execute("""
                INSERT INTO ChamCong (MaNV, MaLLV, NgayChamCong, GioVao, TrangThai)
                VALUES (?, NULL, ?, ?, 0)
            """, (ma_nv, today, now_time))
    conn.commit()
    conn.close()
    
