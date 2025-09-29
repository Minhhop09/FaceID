import cv2
import os
import time
import pyodbc
import face_recognition
from db_utils import get_connection

# ==============================
# Sinh MaNV tự động theo MaPB
# ==============================
def generate_ma_nv(cursor, ma_pb):
    cursor.execute("SELECT MaNV FROM NhanVien WHERE MaPB = ?", (ma_pb,))
    existing = cursor.fetchall()

    max_stt = 0
    for row in existing:
        manv = row[0]  # ví dụ "NVBH3"
        stt_part = manv.replace(f"NV{ma_pb}", "")
        if stt_part.isdigit():
            stt = int(stt_part)
            if stt > max_stt:
                max_stt = stt

    next_stt = max_stt + 1
    return f"NV{ma_pb}{next_stt}"

# ==============================
# Thêm nhân viên mới
# ==============================
def add_new_employee(cursor, conn, ma_nv, hoten, email, ma_pb, sdt, gioitinh, ngaysinh, diachi):
    sql = """
        INSERT INTO NhanVien (MaNV, HoTen, Email, MaPB, SDT, GioiTinh, NgaySinh, DiaChi)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    cursor.execute(sql, (ma_nv, hoten, email, ma_pb, sdt, gioitinh, ngaysinh, diachi))
    conn.commit()
    return ma_nv

# ==============================
# Chụp ảnh nhân viên, trả về path
# ==============================
def capture_photo_and_get_path(ma_nv):
    folder = "photos"
    os.makedirs(folder, exist_ok=True)

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("❌ Không mở được camera")
        return None

    # Delay cho camera ổn định
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
    # Cập nhật nếu đã tồn tại, nếu chưa thì thêm mới
    cursor.execute("""
        IF EXISTS(SELECT 1 FROM KhuonMat WHERE MaNV=? AND TrangThai=1)
            UPDATE KhuonMat
            SET MaHoaNhanDang = ?
            WHERE MaNV=? AND TrangThai=1
        ELSE
            INSERT INTO KhuonMat (MaNV, MaHoaNhanDang, TrangThai)
            VALUES (?, ?, 1)
    """, ma_nv, face_encoding.tobytes(), ma_nv, ma_nv, face_encoding.tobytes())
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
    fullname = input("Nhập họ tên nhân viên: ").strip()
    email = input("Nhập email: ").strip()
    sdt = input("Nhập số điện thoại: ").strip()
    ngaysinh = input("Nhập ngày sinh (YYYY-MM-DD): ").strip()
    diachi = input("Nhập địa chỉ: ").strip()
    gioitinh_input = input("Nhập giới tính (Nam/Nữ): ").strip().lower()
    gioitinh = 1 if gioitinh_input == 'nam' else 0 if gioitinh_input == 'nữ' else None

    if not all([fullname, email, ma_pb, sdt, ngaysinh, diachi, gioitinh is not None]):
        print("❌ Vui lòng điền đầy đủ thông tin hợp lệ")
        conn.close()
        return

    # Sinh MaNV và thêm nhân viên
    ma_nv = generate_ma_nv(cursor, ma_pb)
    ma_nv = add_new_employee(cursor, conn, ma_nv, fullname, email, ma_pb, sdt, gioitinh, ngaysinh, diachi)
    print(f"✅ Thêm nhân viên thành công, MaNV = {ma_nv}")

    # Chụp ảnh
    image_path = capture_photo_and_get_path(ma_nv)
    if image_path:
        encode_and_save(ma_nv, image_path, conn)

    conn.close()

if __name__ == "__main__":
    main()
