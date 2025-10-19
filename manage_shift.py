from db_utils import get_connection

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

def delete_shift(ma_ca):
    conn = get_connection()
    cursor = conn.cursor()

    # ✅ Sử dụng đúng cột MaCa
    cursor.execute("DELETE FROM CaLamViec WHERE MaCa = ?", (ma_ca,))

    conn.commit()
    conn.close()

