from db_utils import get_connection

def get_departments():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM PhongBan")
    data = cursor.fetchall()
    conn.close()
    return data

def add_department(ma_pb, ten_pb):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO PhongBan (MaPB, TenPB) VALUES (?, ?)", (ma_pb, ten_pb))
    conn.commit()
    conn.close()

def update_department(ma_pb, ten_pb):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE PhongBan SET TenPB=? WHERE MaPB=?", (ten_pb, ma_pb))
    conn.commit()
    conn.close()

def delete_department(ma_pb):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM PhongBan WHERE MaPB=?", (ma_pb,))
    conn.commit()
    conn.close()
