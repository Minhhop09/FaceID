from db_utils import get_connection
from flask import session


def get_shifts():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM CaLamViec")
    data = cursor.fetchall()
    conn.close()
    return data

def add_shift(ten_ca, gio_bat_dau, gio_ket_thuc, he_so, mo_ta):
    conn = get_connection()
    cursor = conn.cursor()

    # 🔹 Lấy mã ca hiện có
    cursor.execute("SELECT MaCa FROM CaLamViec")
    existing_codes = [row[0] for row in cursor.fetchall()]

    next_num = 1
    if existing_codes:
        nums = [int(code.replace("Ca", "")) for code in existing_codes if code.startswith("Ca") and code.replace("Ca", "").isdigit()]
        if nums:
            next_num = max(nums) + 1

    new_ma_ca = f"Ca{next_num}"

    # 🔹 Thêm vào CSDL
    cursor.execute("""
        INSERT INTO CaLamViec (MaCa, TenCa, GioBatDau, GioKetThuc, HeSo, MoTa)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (new_ma_ca, ten_ca, gio_bat_dau, gio_ket_thuc, he_so, mo_ta))

    conn.commit()
    conn.close()
    return new_ma_ca


def update_shift(ma_LLV, ma_nv, gio_bat_dau, gio_ket_thuc):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE CaLamViec SET GioBatDau=?, GioKetThuc=? WHERE MaLLV=? WHERE MaNV=?",
                   (gio_bat_dau, gio_ket_thuc, ma_LLV, ma_nv))
    conn.commit()
    conn.close()

def delete_shift(ma_ca_list):
    """
    Xóa mềm 1 hoặc nhiều ca làm việc (cập nhật TrangThai = 0)
    và ghi lại lịch sử thay đổi vào bảng LichSuThayDoi.
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        username = session.get("username", "Hệ thống")  # Lấy tên người thực hiện

        for ma_ca in ma_ca_list:
            # ✅ Cập nhật trạng thái ca làm việc (xóa mềm)
            cursor.execute("""
                UPDATE CaLamViec
                SET TrangThai = 0,
                    NgayCapNhat = GETDATE()
                WHERE MaCa = ?
            """, (ma_ca,))

            # ✅ Ghi lại lịch sử thay đổi
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "CaLamViec",      # Tên bảng
                ma_ca,            # Mã bản ghi bị thay đổi
                "Xóa mềm",        # Hành động
                "TrangThai",      # Trường thay đổi
                "1",              # Giá trị cũ
                "0",              # Giá trị mới
                username           # Người thực hiện
            ))

        conn.commit()
        print(f"✅ Đã xóa mềm {len(ma_ca_list)} ca làm việc.")

    except Exception as e:
        conn.rollback()
        print(f"❌ Lỗi khi xóa mềm ca làm việc: {e}")
        raise e

    finally:
        conn.close()


def restore_shift(ma_ca_list):
    """Khôi phục 1 hoặc nhiều ca làm việc"""
    conn = get_connection()
    cursor = conn.cursor()

    if isinstance(ma_ca_list, str):
        ma_ca_list = [ma_ca_list]

    for ma_ca in ma_ca_list:
        cursor.execute("""
            UPDATE CaLamViec
            SET TrangThai = 1, NgayCapNhat = GETDATE()
            WHERE MaCa = ?
        """, (ma_ca,))

        # Ghi log khôi phục
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, (
            "CaLamViec", ma_ca, "Khôi phục", "TrangThai", 0, 1, session.get("user_id")
        ))

    conn.commit()
    conn.close()

