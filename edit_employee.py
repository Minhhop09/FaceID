import pyodbc

def get_db_connection(server_name="MINHHOP\\SQLEXPRESS", database_name="FaceID"):
    """Tạo kết nối SQL Server"""
    conn_str = f"Driver={{SQL Server}};Server={server_name};Database={database_name};Trusted_Connection=yes;"
    return pyodbc.connect(conn_str)

def find_employees_by_name_or_manv(keyword):
    """
    Tìm nhân viên theo tên hoặc MaNV.
    Trả về danh sách các row
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT MaNV, HoTen, Email, MaPB
        FROM NhanVien
        WHERE HoTen LIKE ? OR MaNV LIKE ?
    """, f"%{keyword}%", f"%{keyword}%")
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_employee_info(ma_nv, new_name=None, new_email=None, new_mapb=None):
    """Cập nhật thông tin nhân viên"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Lấy thông tin hiện tại
    cursor.execute("SELECT HoTen, Email, MaPB FROM NhanVien WHERE MaNV=?", ma_nv)
    row = cursor.fetchone()
    if not row:
        print(f"❌ Không tìm thấy nhân viên với MaNV: {ma_nv}")
        conn.close()
        return

    # Dùng giá trị mới nếu có, nếu không giữ nguyên
    ho_ten = new_name if new_name else row.HoTen
    email = new_email if new_email else row.Email
    ma_pb = new_mapb if new_mapb else row.MaPB

    # Cập nhật vào CSDL
    cursor.execute("""
        UPDATE NhanVien
        SET HoTen=?, Email=?, MaPB=?
        WHERE MaNV=?
    """, ho_ten, email, ma_pb, ma_nv)
    conn.commit()
    conn.close()
    print(f"✅ Cập nhật thông tin nhân viên {ma_nv} thành công.")


# -----------------------------
# Chạy file trực tiếp
# -----------------------------
if __name__ == "__main__":
    print("===== CHỈNH SỬA NHÂN VIÊN =====")
    keyword = input("Nhập tên hoặc MaNV nhân viên cần chỉnh sửa: ").strip()
    if not keyword:
        print("❌ Bạn chưa nhập thông tin tìm kiếm.")
        exit()

    employees = find_employees_by_name_or_manv(keyword)
    if not employees:
        print(f"❌ Không tìm thấy nhân viên với '{keyword}'.")
        exit()

    # Nếu nhiều kết quả, chọn 1
    if len(employees) > 1:
        print("⚠️ Có nhiều nhân viên trùng:")
        for i, emp in enumerate(employees, start=1):
            print(f"{i}. MaNV: {emp.MaNV}, Tên: {emp.HoTen}, Email: {emp.Email}, Phòng ban: {emp.MaPB}")
        choice = input("Nhập số thứ tự nhân viên muốn chỉnh sửa: ").strip()
        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(employees):
                print("❌ Lựa chọn không hợp lệ.")
                exit()
            selected_emp = employees[idx]
        except:
            print("❌ Lựa chọn không hợp lệ.")
            exit()
    else:
        selected_emp = employees[0]

    print("\nThông tin hiện tại:")
    print(f"MaNV: {selected_emp.MaNV}")
    print(f"Tên: {selected_emp.HoTen}")
    print(f"Email: {selected_emp.Email}")
    print(f"Phòng ban: {selected_emp.MaPB}")

    print("\nNhập thông tin mới (để trống nếu không muốn thay đổi):")
    new_name = input("Tên mới: ").strip()
    new_email = input("Email mới: ").strip()
    new_mapb = input("Mã phòng ban mới: ").strip()

    confirm = input("Bạn có chắc chắn muốn cập nhật? (y/n): ").lower()
    if confirm == 'y':
        update_employee_info(selected_emp.MaNV, new_name, new_email, new_mapb)
    else:
        print("❌ Hủy thao tác chỉnh sửa.")
