import cv2
import os
import time
import pyodbc
import face_recognition
from datetime import datetime
from db_utils import get_connection


# ==============================
# Sinh MaNV tự động theo MaPB
# ==============================
def generate_ma_nv(ma_pb):
    conn = get_connection()
    cursor = conn.cursor()

    # Lấy tất cả mã nhân viên trong phòng ban đó
    cursor.execute("SELECT MaNV FROM NhanVien WHERE MaPB = ?", (ma_pb,))
    existing = cursor.fetchall()

    # Lấy tên phòng ban để sinh viết tắt (ví dụ: Tài chính → TC)
    cursor.execute("SELECT TenPB FROM PhongBan WHERE MaPB = ?", (ma_pb,))
    ten_pb_row = cursor.fetchone()
    viet_tat = ""
    if ten_pb_row:
        ten_pb = ten_pb_row[0]
        viet_tat = "".join(word[0].upper() for word in ten_pb.split())

    # Tìm số thứ tự cao nhất
    max_stt = 0
    for row in existing:
        manv = row[0]  # ví dụ: NVTC3
        digits = ''.join(filter(str.isdigit, manv))
        if digits.isdigit():
            num = int(digits)
            if num > max_stt:
                max_stt = num

    new_ma_nv = f"NV{viet_tat}{max_stt + 1}"

    conn.close()
    return new_ma_nv


# ==============================
# Thêm nhân viên mới
# ==============================
def add_new_employee(cursor, conn, ma_nv, hoten, email, sdt, gioitinh, ngaysinh, diachi, ma_pb, chucvu):
    """
    Thứ tự cột trong bảng NhanVien (bỏ LuongGioCoBan):
    MaNV, HoTen, Email, SDT, GioiTinh, NgaySinh, DiaChi, MaPB, ChucVu,
    TrangThai, NgayVaoLam, NgayNghiViec, NgayTao
    """
    sql = """
        INSERT INTO NhanVien (
            MaNV, HoTen, Email, SDT, GioiTinh, NgaySinh, DiaChi, MaPB, ChucVu,
            TrangThai, NgayVaoLam, NgayNghiViec, NgayTao
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    trangthai = 1  # 1 = Đang làm việc
    ngay_vao_lam = datetime.now().date()
    ngay_tao = datetime.now().date()
    ngay_nghi_viec = None

    cursor.execute(sql, (
        ma_nv, hoten, email, sdt, gioitinh, ngaysinh, diachi, ma_pb, chucvu,
        trangthai, ngay_vao_lam, ngay_nghi_viec, ngay_tao
    ))
    conn.commit()
    return ma_nv


# ==============================
# Chụp ảnh nhân viên
# ==============================
def capture_photo_and_get_path(ma_nv):
    folder = "photos"
    os.makedirs(folder, exist_ok=True)

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("❌ Không mở được camera")
        return None

    time.sleep(1)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print("❌ Không chụp được ảnh")
        return None

    filename = os.path.join(folder, f"{ma_nv}_{int(time.time())}.jpg")
    cv2.imwrite(filename, frame)
    print(f"✅ Ảnh đã lưu: {filename}")
    return filename


# ==============================
# Encode ảnh và lưu vào KhuonMat
# ==============================
def encode_and_save(ma_nv, image_path, conn):
    image = face_recognition.load_image_file(image_path)
    encodings = face_recognition.face_encodings(image)
    if len(encodings) == 0:
        print("❌ Không nhận diện được khuôn mặt")
        return False

    face_encoding = encodings[0]
    cursor = conn.cursor()

    cursor.execute("""
        IF EXISTS(SELECT 1 FROM KhuonMat WHERE MaNV=? AND TrangThai=1)
            UPDATE KhuonMat
            SET MaHoaNhanDang = ?
            WHERE MaNV=? AND TrangThai=1
        ELSE
            INSERT INTO KhuonMat (MaNV, MaHoaNhanDang, TrangThai)
            VALUES (?, ?, 1)
    """, (ma_nv, face_encoding.tobytes(), ma_nv, ma_nv, face_encoding.tobytes()))

    conn.commit()
    print(f"✅ Khuôn mặt của {ma_nv} đã được lưu vào KhuonMat")
    return True


# ==============================
# Main nhập liệu và đăng ký
# ==============================
def main():
    conn = get_connection()
    if conn is None:
        print("❌ Không thể kết nối database")
        return

    cursor = conn.cursor()

    # Nhập thông tin nhân viên
    ma_pb = input("Nhập mã phòng ban: ").strip()
    hoten = input("Nhập họ tên nhân viên: ").strip()
    email = input("Nhập email: ").strip()
    sdt = input("Nhập số điện thoại: ").strip()
    ngaysinh = input("Nhập ngày sinh (YYYY-MM-DD): ").strip()
    diachi = input("Nhập địa chỉ: ").strip()
    chucvu = input("Nhập chức vụ: ").strip()
    gioitinh_input = input("Nhập giới tính (Nam/Nữ): ").strip().lower()
    gioitinh = 1 if gioitinh_input == "nam" else 0 if gioitinh_input == "nữ" else None

    if not all([hoten, email, ma_pb, sdt, ngaysinh, chucvu, diachi]) or gioitinh is None:
        print("❌ Vui lòng điền đầy đủ thông tin hợp lệ")
        conn.close()
        return

    # Sinh mã nhân viên và thêm vào DB
    ma_nv = generate_ma_nv(ma_pb)
    ma_nv = add_new_employee(cursor, conn, ma_nv, hoten, email, sdt, gioitinh, ngaysinh, diachi, ma_pb, chucvu)
    print(f"✅ Thêm nhân viên thành công, MaNV = {ma_nv}")

    # Chụp ảnh và lưu khuôn mặt
    image_path = capture_photo_and_get_path(ma_nv)
    if image_path:
        encode_and_save(ma_nv, image_path, conn)

    conn.close()


if __name__ == "__main__":
    main()
