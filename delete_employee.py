import pyodbc
import os

def get_db_connection(server_name="MINHHOP\\SQLEXPRESS", database_name="FaceID"):
    """Tạo kết nối SQL Server"""
    conn_str = f"Driver={{SQL Server}};Server={server_name};Database={database_name};Trusted_Connection=yes;"
    return pyodbc.connect(conn_str)

def find_employees_by_name(ten_nv):
    """Tìm tất cả nhân viên theo tên (có thể trùng)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MaNV, HoTen, Email, MaPB FROM NhanVien WHERE HoTen LIKE ?", f"%{ten_nv}%")
    rows = cursor.fetchall()
    conn.close()
    return rows

def delete_employee_by_ma_nv(ma_nv):
    """Xóa nhân viên theo MaNV"""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Lấy danh sách ảnh
    cursor.execute("SELECT DuongDanAnh FROM KhuonMat WHERE MaNV=?", ma_nv)
    rows = cursor.fetchall()
    for r in rows:
        path = r.DuongDanAnh
        if os.path.exists(path):
            os.remove(path)
            print(f"✅ Đã xóa file ảnh: {path}")

    # Xóa dữ liệu khuôn mặt
    cursor.execute("DELETE FROM KhuonMat WHERE MaNV=?", ma_nv)
    print(f"✅ Đã xóa dữ liệu khuôn mặt của {ma_nv}")

    # Xóa nhân viên
    cursor.execute("DELETE FROM NhanVien WHERE MaNV=?", ma_nv)
    print(f"✅ Đã xóa nhân viên {ma_nv}")

    conn.commit()
    conn.close()
    print("✅ Hoàn tất xóa nhân viên và dữ liệu liên quan.\n")

# -----------------------------
# Chạy file trực tiếp
# -----------------------------
if __name__ == "__main__":
    print("===== XÓA NHÂN VIÊN =====")
    ten_nv = input("Nhập tên nhân viên cần xóa: ").strip()
    if not ten_nv:
        print("❌ Bạn chưa nhập tên nhân viên.")
        exit()

    employees = find_employees_by_name(ten_nv)
    if not employees:
        print(f"❌ Không tìm thấy nhân viên có tên '{ten_nv}'.")
        exit()

    # Nếu nhiều nhân viên trùng tên
    if len(employees) > 1:
        print("⚠️ Có nhiều nhân viên trùng tên:")
        for i, emp in enumerate(employees, start=1):
            print(f"{i}. MaNV: {emp.MaNV}, Tên: {emp.HoTen}, Email: {emp.Email}, Phòng ban: {emp.MaPB}")
        choice = input("Nhập số thứ tự nhân viên muốn xóa: ").strip()
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

    print("\nThông tin nhân viên sẽ xóa:")
    print(f"MaNV: {selected_emp.MaNV}")
    print(f"Tên: {selected_emp.HoTen}")
    print(f"Email: {selected_emp.Email}")
    print(f"Phòng ban: {selected_emp.MaPB}")

    confirm = input("Bạn có chắc chắn muốn xóa nhân viên này? (y/n): ").lower()
    if confirm == 'y':
        delete_employee_by_ma_nv(selected_emp.MaNV)
    else:
        print("❌ Hủy thao tác xóa.")
