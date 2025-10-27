import pyodbc
from datetime import datetime
from core.db_utils import get_sql_connection


# ============================================================
# 🧾 Ghi log thay đổi dữ liệu (dành cho CRUD)
# ============================================================
def log_change(ten_bang, ma_ban_ghi, hanh_dong, truong_thay_doi, du_lieu_cu, du_lieu_moi, nguoi_thuc_hien):
    """
    Ghi log khi dữ liệu thay đổi (thêm/sửa/xóa...).
    Dùng cho các thao tác CRUD hoặc trigger ứng dụng.
    """
    conn = None
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO LichSuThayDoi
                (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, (ten_bang, ma_ban_ghi, hanh_dong, truong_thay_doi, du_lieu_cu, du_lieu_moi, nguoi_thuc_hien))
        conn.commit()
        print(f"[LOG] ✅ Ghi log thay đổi: {ten_bang}.{truong_thay_doi} ({hanh_dong})")
    except Exception as e:
        print(f"[WARN] ⚠️ Lỗi ghi lịch sử thay đổi ({hanh_dong}): {e}")
    finally:
        if conn:
            conn.close()


# ============================================================
# 🧾 Ghi log hoạt động hệ thống (xem, tính lương, đăng nhập...)
# ============================================================
def ghi_lich_su(ten_bang, ma_ban_ghi, hanh_dong, gia_tri_moi, nguoi_thuc_hien, ip, device, scope):
    """
    Ghi log hoạt động người dùng vào bảng LichSuThayDoi.
    Dùng cho hành động như: Xem danh sách, Tính lương, Đăng nhập, Xuất file...
    """
    conn_log = None
    try:
        conn_log = get_sql_connection()
        cur = conn_log.cursor()
        cur.execute("""
            INSERT INTO LichSuThayDoi
                (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi,
                 ThoiGian, NguoiThucHien, IPAddress, DeviceID, Scope)
            VALUES (?, ?, ?, NULL, NULL, ?, GETDATE(), ?, ?, ?, ?)
        """, (ten_bang, ma_ban_ghi, hanh_dong, gia_tri_moi, nguoi_thuc_hien, ip, device, scope))
        conn_log.commit()
        print(f"[LOG] 🧾 {nguoi_thuc_hien} - {hanh_dong} ({scope})")
    except Exception as err:
        print(f"[WARN] ⚠️ Không thể ghi log ({hanh_dong}): {err}")
    finally:
        if conn_log:
            conn_log.close()


# ============================================================
# 💳 Ghi log thanh toán lương (giao dịch)
# ============================================================
def log_payment(ma_luong, ma_nv, so_tien, phuong_thuc,
                ma_giaodich, phi_gd, ket_qua, nguoi_thuc_hien,
                ip, device):
    """
    Ghi log khi thanh toán lương (thành công hoặc thất bại).
    Lưu thông tin chi tiết giao dịch và trạng thái.
    """
    conn = None
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()
        device_safe = (device or "")[:500]
        noi_dung = (
            f"Thanh toán {so_tien:,}đ qua {phuong_thuc.upper()} "
            f"(Mã GD: {ma_giaodich}, Phí: {phi_gd:,}đ, Kết quả: {ket_qua})"
        )

        cursor.execute("""
            INSERT INTO LichSuThayDoi
                (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi,
                 ThoiGian, NguoiThucHien, IPAddress, DeviceID, Scope)
            VALUES (N'Luong', ?, N'Thanh toán lương', NULL, NULL, ?, 
                    GETDATE(), ?, ?, ?, N'PAYMENT')
        """, (ma_luong, noi_dung, nguoi_thuc_hien, ip, device_safe))

        conn.commit()
        print(f"[LOG] 💸 Ghi log thanh toán lương {ma_luong} ({ket_qua})")
    except Exception as e:
        print(f"[WARN] ⚠️ Không thể ghi log thanh toán: {e}")
    finally:
        if conn:
            conn.close()