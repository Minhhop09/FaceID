import pyodbc
import os
import cv2
import time
from encode_save import encode_and_save  # hàm encode và lưu FaceID

# ----------------------------
# Kết nối CSDL
# ----------------------------
def get_db_connection(server_name="MINHHOP\\SQLEXPRESS", database_name="FaceID"):
    conn_str = f"Driver={{SQL Server}};Server={server_name};Database={database_name};Trusted_Connection=yes;"
    return pyodbc.connect(conn_str)

# ----------------------------
# THÊM NHÂN VIÊN
# ----------------------------
def add_employee():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Nhập thông tin
    ho_ten = input("Nhập tên nhân viên: ").strip()
    email = input("Nhập email: ").strip()
    ma_pb = input("Nhập mã phòng ban: ").strip()

    # Tạo MaNV tự động: NV + MaPB + số thứ tự
    cursor.execute("SELECT COUNT(*) FROM NhanVien WHERE MaNV LIKE ?", f"NV{ma_pb}%")
    count = cursor.fetchone()[0] + 1
    ma_nv = f"NV{ma_pb}{count}"

    # Thêm nhân viên vào DB
    cursor.execute("INSERT INTO NhanVien (MaNV, HoTen, Email, MaPB) VALUES (?, ?, ?, ?)", ma_nv, ho_ten, email, ma_pb)
    conn.commit()
    conn.close()
    print(f"✅ Thêm nhân viên thành công, MaNV = {ma_nv}")

    # Chụp ảnh và lưu FaceID
    capture_photo_and_save(ma_nv)

# ----------------------------
# CHỤP ẢNH VÀ LƯU FACEID
# ----------------------------
def capture_photo_and_save(ma_nv):
    folder = "photos"
    if not os.path.exists(folder):
        os.makedirs(folder)

    cap = cv2.VideoCapture(0)
    cv2.namedWindow("Capture Photo")
    print("📷 Nhấn 'c' để chụp, 'q' để thoát.")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue
        cv2.imshow("Capture Photo", frame)
        key = cv2.waitKey(1) & 0xFF

        if key == ord("c"):
            timestamp = int(time.time())
            filename = os.path.join(folder, f"person{ma_nv}_{timestamp}.jpg")
            cv2.imwrite(filename, frame)
            print(f"✅ Ảnh đã lưu: {filename}")

            # Encode và lưu vào CSDL
            try:
                conn = get_db_connection()
                encode_and_save(ma_nv, filename, conn)
            except Exception as e:
                print(f"❌ Lỗi khi lưu vào CSDL: {e}")
            finally:
                conn.close()
            break

        elif key == ord("q"):
            print("Thoát mà không lưu ảnh.")
            break

    cap.release()
    cv2.destroyAllWindows()

# ----------------------------
# XÓA NHÂN VIÊN
# ----------------------------
def delete_employee():
    ten_nv = input("Nhập tên nhân viên cần xóa: ").strip()
    if not ten_nv:
        print("❌ Chưa nhập tên.")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MaNV, HoTen, Email, MaPB FROM NhanVien WHERE HoTen LIKE ?", f"%{ten_nv}%")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"❌ Không tìm thấy nhân viên có tên '{ten_nv}'")
        return

    # Chọn nhân viên nếu trùng
    if len(rows) > 1:
        print("⚠️ Có nhiều nhân viên trùng tên:")
        for i, emp in enumerate(rows, start=1):
            print(f"{i}. MaNV: {emp.MaNV}, Tên: {emp.HoTen}, Email: {emp.Email}, Phòng ban: {emp.MaPB}")
        choice = input("Nhập số thứ tự nhân viên muốn xóa: ").strip()
        try:
            idx = int(choice) - 1
            selected_emp = rows[idx]
        except:
            print("❌ Lựa chọn không hợp lệ.")
            return
    else:
        selected_emp = rows[0]

    print(f"Bạn sắp xóa nhân viên: {selected_emp.HoTen} ({selected_emp.MaNV})")
    confirm = input("Xác nhận xóa? (y/n): ").lower()
    if confirm != 'y':
        print("❌ Hủy thao tác.")
        return

    # Xóa ảnh
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DuongDanAnh FROM KhuonMat WHERE MaNV=?", selected_emp.MaNV)
    photos = cursor.fetchall()
    for p in photos:
        path = p.DuongDanAnh
        if os.path.exists(path):
            os.remove(path)
            print(f"✅ Đã xóa file ảnh: {path}")

    # Xóa dữ liệu khuôn mặt và nhân viên
    cursor.execute("DELETE FROM KhuonMat WHERE MaNV=?", selected_emp.MaNV)
    cursor.execute("DELETE FROM NhanVien WHERE MaNV=?", selected_emp.MaNV)
    conn.commit()
    conn.close()
    print(f"✅ Đã xóa nhân viên {selected_emp.MaNV} và dữ liệu liên quan.")

# ----------------------------
# CHỈNH SỬA NHÂN VIÊN
# ----------------------------
def edit_employee():
    keyword = input("Nhập tên hoặc MaNV nhân viên muốn chỉnh sửa: ").strip()
    if not keyword:
        print("❌ Chưa nhập thông tin.")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MaNV, HoTen, Email, MaPB FROM NhanVien WHERE HoTen LIKE ? OR MaNV LIKE ?", f"%{keyword}%", f"%{keyword}%")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print(f"❌ Không tìm thấy nhân viên '{keyword}'")
        return

    # Chọn nhân viên nếu nhiều
    if len(rows) > 1:
        print("⚠️ Có nhiều nhân viên trùng:")
        for i, emp in enumerate(rows, start=1):
            print(f"{i}. MaNV: {emp.MaNV}, Tên: {emp.HoTen}, Email: {emp.Email}, Phòng ban: {emp.MaPB}")
        choice = input("Nhập số thứ tự nhân viên muốn chỉnh sửa: ").strip()
        try:
            idx = int(choice) - 1
            selected_emp = rows[idx]
        except:
            print("❌ Lựa chọn không hợp lệ.")
            return
    else:
        selected_emp = rows[0]

    print("\nThông tin hiện tại:")
    print(f"Tên: {selected_emp.HoTen}")
    print(f"Email: {selected_emp.Email}")
    print(f"Phòng ban: {selected_emp.MaPB}")

    # Nhập thông tin mới
    new_name = input("Tên mới (để trống giữ nguyên): ").strip()
    new_email = input("Email mới (để trống giữ nguyên): ").strip()
    new_mapb = input("Mã phòng ban mới (để trống giữ nguyên): ").strip()

    confirm = input("Xác nhận cập nhật? (y/n): ").lower()
    if confirm != 'y':
        print("❌ Hủy thao tác.")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE NhanVien SET HoTen=?, Email=?, MaPB=? WHERE MaNV=?
    """,
    new_name if new_name else selected_emp.HoTen,
    new_email if new_email else selected_emp.Email,
    new_mapb if new_mapb else selected_emp.MaPB,
    selected_emp.MaNV)
    conn.commit()
    conn.close()
    print(f"✅ Cập nhật thông tin nhân viên {selected_emp.MaNV} thành công.")

# ----------------------------
# HIỂN THỊ DANH SÁCH NHÂN VIÊN
# ----------------------------
def list_employees():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MaNV, HoTen, Email, MaPB FROM NhanVien")
    rows = cursor.fetchall()
    conn.close()
    print("===== DANH SÁCH NHÂN VIÊN =====")
    for emp in rows:
        print(f"MaNV: {emp.MaNV}, Tên: {emp.HoTen}, Email: {emp.Email}, Phòng ban: {emp.MaPB}")
    print("================================")

# ----------------------------
# MENU CHÍNH
# ----------------------------
def main_menu():
    while True:
        print("\n===== QUẢN LÝ NHÂN VIÊN =====")
        print("1. Thêm nhân viên")
        print("2. Xóa nhân viên")
        print("3. Chỉnh sửa nhân viên")
        print("4. Danh sách nhân viên")
        print("0. Thoát")
        choice = input("Chọn chức năng: ").strip()

        if choice == '1':
            add_employee()
        elif choice == '2':
            delete_employee()
        elif choice == '3':
            edit_employee()
        elif choice == '4':
            list_employees()
        elif choice == '0':
            print("✅ Thoát chương trình.")
            break
        else:
            print("❌ Lựa chọn không hợp lệ.")

if __name__ == "__main__":
    main_menu()
