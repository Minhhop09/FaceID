from db_utils import get_connection

def attendance_report(start_date, end_date):
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT nv.MaNV, nv.HoTen, COUNT(*) AS SoNgayCong
        FROM ChamCong cc
        JOIN NhanVien nv ON cc.MaNV = nv.MaNV
        WHERE cc.Ngay BETWEEN ? AND ?
        GROUP BY nv.MaNV, nv.HoTen
    """
    cursor.execute(query, (start_date, end_date))
    data = cursor.fetchall()
    conn.close()
    return data

def department_report():
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT pb.TenPB, COUNT(nv.MaNV) AS SoNhanVien
        FROM PhongBan pb
        LEFT JOIN NhanVien nv ON pb.MaPB = nv.MaPB
        GROUP BY pb.TenPB
    """
    cursor.execute(query)
    data = cursor.fetchall()
    conn.close()
    return data

def shift_report():
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT cl.MaCa, COUNT(cc.MaNV) AS SoLanChamCong
        FROM CaLamViec cl
        LEFT JOIN ChamCong cc ON cl.MaCa = cc.MaCa
        GROUP BY cl.MaCa
    """
    cursor.execute(query)
    data = cursor.fetchall()
    conn.close()
    return data
