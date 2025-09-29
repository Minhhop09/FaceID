import face_recognition
import datetime

def encode_and_save(nhanvien_id, image_path, conn):
    """
    Encode khuôn mặt từ ảnh và lưu vào CSDL
    nhanvien_id: MaNV
    image_path: đường dẫn file ảnh
    conn: kết nối SQL Server
    """
    # Load ảnh
    image = face_recognition.load_image_file(image_path)
    encodings = face_recognition.face_encodings(image)

    # Kiểm tra có khuôn mặt không
    if len(encodings) == 0:
        print("⚠️ Không phát hiện khuôn mặt:", image_path)
        return False

    # Lấy vector encode đầu tiên
    face_encoding = encodings[0]
    face_encoding_bytes = face_encoding.tobytes()  # lưu dạng VARBINARY

    ngay_dang_ky = datetime.datetime.now()
    trang_thai = 1
    mo_ta = "Khuôn mặt đã đăng ký"

    cursor = conn.cursor()
    sql = """
        INSERT INTO KhuonMat (MaNV, DuongDanAnh, MaHoaNhanDang, NgayDangKy, TrangThai, MoTa)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    cursor.execute(sql, nhanvien_id, image_path, face_encoding_bytes, ngay_dang_ky, trang_thai, mo_ta)
    conn.commit()

    print(f"✅ Khuôn mặt của {nhanvien_id} đã lưu vào CSDL.")
    return True
