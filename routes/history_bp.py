# ============================================================
# 📘 routes/history_bp.py — FINAL VERSION (Hiển thị 4 loại lịch sử)
# ============================================================
from flask import Blueprint, render_template, request, session, flash
from core.db_utils import get_sql_connection
from core.decorators import require_role

history_bp = Blueprint("history_bp", __name__)

# ============================================================
# 🕒 LỊCH SỬ HỆ THỐNG (TỔNG HỢP)
# ============================================================
@history_bp.route("/history")
@require_role("admin")
def history():
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Tham số lọc ---
    selected_type = request.args.get("type", "all")  # all | thaydoi | hethong | email | giaodich
    selected_table = request.args.get("table", "")
    selected_action = request.args.get("action", "")
    keyword_user = request.args.get("user", "").strip()

    try:
        # ============================================================
        # 1️⃣ Chọn loại lịch sử
        # ============================================================
        if selected_type == "thaydoi":
            query = """
                SELECT 
                    'LichSuThayDoi' AS Loai,
                    TenBang AS Nguon,
                    MaBanGhi AS MaGhi,
                    HanhDong,
                    TruongThayDoi,
                    GiaTriCu,
                    GiaTriMoi,
                    ThoiGian,
                    COALESCE(tk.TenDangNhap, ls.NguoiThucHien) AS NguoiThucHien,
                    ls.IPAddress,
                    ls.DeviceID,
                    ls.Scope
                FROM LichSuThayDoi ls
                LEFT JOIN TaiKhoan tk ON TRY_CAST(ls.NguoiThucHien AS INT) = tk.MaTK
                WHERE 1=1
            """
        elif selected_type == "hethong":
            query = """
                SELECT 
                    'LichSuHeThong' AS Loai,
                    HanhDong AS Nguon,
                    NoiDung AS MaGhi,
                    KetQua AS HanhDong,
                    IP AS TruongThayDoi,
                    ThietBi AS GiaTriCu,
                    NULL AS GiaTriMoi,
                    ThoiGian,
                    NguoiThucHien,
                    IP AS IPAddress,
                    ThietBi AS DeviceID,
                    Scope
                FROM LichSuHeThong
                WHERE 1=1
            """
        elif selected_type == "email":
            query = """
                SELECT 
                    'LichSuEmail' AS Loai,
                    LoaiThongBao AS Nguon,
                    EmailTo AS MaGhi,
                    TrangThai AS HanhDong,
                    NULL AS TruongThayDoi,
                    NULL AS GiaTriCu,
                    NULL AS GiaTriMoi,
                    ThoiGian,
                    NULL AS NguoiThucHien,
                    NULL AS IPAddress,
                    NULL AS DeviceID,
                    NULL AS Scope
                FROM LichSuEmail
                WHERE 1=1
            """
        elif selected_type == "giaodich":
            query = """
                SELECT 
                    'GiaoDichLuong' AS Loai,
                    MaLuong AS Nguon,
                    MaGiaoDich AS MaGhi,
                    TrangThai AS HanhDong,
                    PhuongThuc AS TruongThayDoi,
                    PhiGiaoDich AS GiaTriCu,
                    NoiDung AS GiaTriMoi,
                    NgayGiaoDich AS ThoiGian,
                    NguoiThucHien,
                    NULL AS IPAddress,
                    NULL AS DeviceID,
                    NULL AS Scope
                FROM GiaoDichLuong
                WHERE 1=1
            """
        else:
            # Tổng hợp tất cả
            query = """
                SELECT 
                    'LichSuThayDoi' AS Loai,
                    TenBang AS Nguon,
                    MaBanGhi AS MaGhi,
                    HanhDong,
                    TruongThayDoi,
                    GiaTriCu,
                    GiaTriMoi,
                    ThoiGian,
                    COALESCE(tk.TenDangNhap, ls.NguoiThucHien) AS NguoiThucHien,
                    ls.IPAddress,
                    ls.DeviceID,
                    ls.Scope
                FROM LichSuThayDoi ls
                LEFT JOIN TaiKhoan tk ON TRY_CAST(ls.NguoiThucHien AS INT) = tk.MaTK

                UNION ALL

                SELECT 
                    'LichSuHeThong', HanhDong, NoiDung, KetQua, IP, ThietBi, NULL, ThoiGian,
                    NguoiThucHien, IP, ThietBi, Scope
                FROM LichSuHeThong

                UNION ALL

                SELECT 
                    'LichSuEmail', LoaiThongBao, EmailTo, TrangThai, NULL, NULL, NULL, ThoiGian,
                    NULL, NULL, NULL, NULL
                FROM LichSuEmail

                UNION ALL

                SELECT 
                    'GiaoDichLuong', MaLuong, MaGiaoDich, TrangThai, PhuongThuc, PhiGiaoDich, NoiDung,
                    NgayGiaoDich, NguoiThucHien, NULL, NULL, NULL
                FROM GiaoDichLuong
            """

        # ============================================================
        # 2️⃣ Lọc theo người dùng (LIKE)
        # ============================================================
        params = []
        if keyword_user:
            query += " AND (NguoiThucHien LIKE ? OR Nguon LIKE ?)"
            like_pattern = f"%{keyword_user}%"
            params.extend([like_pattern, like_pattern])

        # ============================================================
        # 3️⃣ Lọc thêm nếu có bảng hoặc hành động
        # ============================================================
        if selected_table and selected_type == "thaydoi":
            query += " AND Nguon = ?"
            params.append(selected_table)
        if selected_action and selected_type == "thaydoi":
            query += " AND HanhDong = ?"
            params.append(selected_action)

        query += " ORDER BY ThoiGian DESC"

        # ============================================================
        # 4️⃣ Truy vấn dữ liệu
        # ============================================================
        cursor.execute(query, params)
        histories = cursor.fetchall()

        # ============================================================
        # 5️⃣ Lấy danh sách bảng + hành động
        # ============================================================
        cursor.execute("SELECT DISTINCT TenBang FROM LichSuThayDoi ORDER BY TenBang")
        table_names = [r[0] for r in cursor.fetchall()]

        cursor.execute("""
            SELECT DISTINCT HanhDong 
            FROM LichSuThayDoi 
            WHERE HanhDong IN (N'Thêm', N'Sửa', N'Xóa', N'Khôi phục', N'Xem chi tiết')
            ORDER BY HanhDong
        """)
        action_names = [r[0] for r in cursor.fetchall()]

    except Exception as e:
        flash(f"❌ Lỗi khi tải lịch sử: {e}", "danger")
        histories, table_names, action_names = [], [], []
    finally:
        conn.close()

    return render_template(
        "history.html",
        histories=histories,
        tables=table_names,
        actions=action_names,
        selected_type=selected_type,
        selected_table=selected_table,
        selected_action=selected_action,
        keyword_user=keyword_user
    )
