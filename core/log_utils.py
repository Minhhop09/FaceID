import pyodbc
from datetime import datetime
from core.db_utils import get_sql_connection

def log_change(bang, ma_banghi, hanh_dong, du_lieu_cu, du_lieu_moi, nguoi_thuchien):
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO LichSuThayDoi (Bang, MaBanGhi, HanhDong, DuLieuCu, DuLieuMoi, ThoiGian, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (bang, ma_banghi, hanh_dong, du_lieu_cu, du_lieu_moi, datetime.now(), nguoi_thuchien))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Lỗi ghi lịch sử: {e}")
