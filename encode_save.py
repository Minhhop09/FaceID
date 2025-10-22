import face_recognition
import datetime
import pyodbc

def encode_and_save(nhanvien_id, image_path, conn):
    """
    Encode khuôn mặt từ ảnh và lưu vào CSDL
    nhanvien_id: MaNV
    image_path: đường dẫn file ảnh
    conn: kết nối SQL Server
    """
    # Load ảnh và encode
    image = face_recognition.load_image_file(image_path)
    encodings = face_recognition.face_encodings(image)
    if len(encodings) == 0:
        print("⚠️ Không phát hiện khuôn mặt:", image_path)
        return False

    face_encoding = encodings[0]
    face_encoding_bytes = face_encoding.tobytes()  # lưu dạng VARBINARY

    ngay_dang_ky = datetime.datetime.now()
    trang_thai = 1
    mo_ta = "Khuôn mặt đã đăng ký"

    cursor = conn.cursor()

    # Kiểm tra xem đã có khuôn mặt với MaNV và TrangThai=1 chưa
    cursor.execute("""
        SELECT COUNT(*) FROM KhuonMat
        WHERE MaNV=? AND TrangThai=1
    """, (nhanvien_id,))
    exists = cursor.fetchone()[0]

    if exists:
        # Nếu có rồi, update lại
        sql = """
            UPDATE KhuonMat
            SET DuongDanAnh=?, MaHoaNhanDang=?, NgayDangKy=?, MoTa=?
            WHERE MaNV=? AND TrangThai=1
        """
        cursor.execute(sql, (image_path, face_encoding_bytes, ngay_dang_ky, mo_ta, nhanvien_id))
        print(f"🔄 Cập nhật khuôn mặt của {nhanvien_id} trong CSDL.")
    else:
        # Nếu chưa có, insert mới
        sql = """
            INSERT INTO KhuonMat (MaNV, DuongDanAnh, MaHoaNhanDang, NgayDangKy, TrangThai, MoTa)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        cursor.execute(sql, (nhanvien_id, image_path, face_encoding_bytes, ngay_dang_ky, trang_thai, mo_ta))
        print(f"✅ Khuôn mặt của {nhanvien_id} đã lưu vào CSDL.")

    conn.commit()
    return True
