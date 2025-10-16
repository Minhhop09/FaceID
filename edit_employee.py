# edit_employee.py
from db_utils import get_sql_connection
from flask import flash

def edit_employee(ma_nv, form_data):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # Lấy nhân viên
    cursor.execute("""
        SELECT MaNV, HoTen, Email, SDT, GioiTinh, NgaySinh, DiaChi, MaPB, ChucVu, TrangThai
        FROM NhanVien WHERE MaNV=?
    """, (ma_nv,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "Không tìm thấy nhân viên"

    employee = dict(zip([c[0] for c in cursor.description], row))

    # Lấy dữ liệu form, giữ nguyên nếu để trống
    hoten = form_data.get("hoten") or employee.get("HoTen")
    email = form_data.get("email") or employee.get("Email")
    sdt = form_data.get("sdt") or employee.get("SDT")
    gioitinh = form_data.get("gioitinh")
    ngaysinh = form_data.get("ngaysinh") or employee.get("NgaySinh")
    diachi = form_data.get("diachi") or employee.get("DiaChi")
    ma_pb = form_data.get("mapb") or employee.get("MaPB")
    chucvu = form_data.get("chucvu") or employee.get("ChucVu")
    trangthai = form_data.get("trangthai") or employee.get("TrangThai")

    # Cập nhật
    cursor.execute("""
        UPDATE NhanVien
        SET HoTen=?, Email=?, SDT=?, GioiTinh=?, NgaySinh=?, DiaChi=?, MaPB=?, ChucVu=?, TrangThai=?
        WHERE MaNV=?
    """, (hoten, email, sdt, gioitinh, ngaysinh, diachi, ma_pb, chucvu, trangthai, ma_nv))

    conn.commit()
    conn.close()
    return True, "Cập nhật thành công"
