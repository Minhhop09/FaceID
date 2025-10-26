from core.db_utils import get_sql_connection

def generate_ma_nv():
    """
    Sinh mã nhân viên tự động dạng NV00001, NV00002, ...
    """
    conn = get_sql_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT MaNV FROM NhanVien")
    existing = [row[0] for row in cursor.fetchall()]

    max_num = 0
    for manv in existing:
        digits = "".join(filter(str.isdigit, manv))
        if digits.isdigit():
            num = int(digits)
            if num > max_num:
                max_num = num

    conn.close()
    new_num = max_num + 1
    return f"NV{new_num:05d}"

def add_new_employee(cursor, conn, ma_nv, ho_ten, email, sdt, gioi_tinh, ngay_sinh, dia_chi, ma_pb, chuc_vu):
    """Thêm nhân viên mới vào bảng NhanVien."""
    cursor.execute("""
        INSERT INTO NhanVien (MaNV, HoTen, Email, SDT, GioiTinh, NgaySinh, DiaChi, MaPB, ChucVu, TrangThai)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (ma_nv, ho_ten, email, sdt, gioi_tinh, ngay_sinh, dia_chi, ma_pb, chuc_vu))
    conn.commit()
