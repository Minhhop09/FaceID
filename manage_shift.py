from db_utils import get_connection

def get_shifts():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM CaLamViec")
    data = cursor.fetchall()
    conn.close()
    return data

def add_shift(ma_ca, gio_bat_dau, gio_ket_thuc):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO CaLamViec (MaCa, GioBatDau, GioKetThuc) VALUES (?, ?, ?)",
                   (ma_ca, gio_bat_dau, gio_ket_thuc))
    conn.commit()
    conn.close()

def update_shift(ma_ca, gio_bat_dau, gio_ket_thuc):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE CaLamViec SET GioBatDau=?, GioKetThuc=? WHERE MaCa=?",
                   (gio_bat_dau, gio_ket_thuc, ma_ca))
    conn.commit()
    conn.close()

def delete_shift(ma_ca):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM CaLamViec WHERE MaCa=?", (ma_ca,))
    conn.commit()
    conn.close()
