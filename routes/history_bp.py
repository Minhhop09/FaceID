# routes/history_bp.py
from flask import Blueprint, render_template, request, session, flash
from core.db_utils import get_sql_connection
from core.decorators import require_role  # hoặc import require_role từ đúng nơi bạn định nghĩa

history_bp = Blueprint("history_bp", __name__)

# ============================================================
# 🕒 LỊCH SỬ THAY ĐỔI (ADMIN)
# ============================================================
@history_bp.route("/history")
@require_role("admin")
def history():
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy tham số từ form hoặc query ---
    selected_table = request.args.get("table")
    selected_action = request.args.get("action")
    keyword_user = request.args.get("user", "").strip()

    # --- Câu truy vấn chính ---
    base_query = """
        SELECT 
            ls.*, 
            COALESCE(tk.TenDangNhap, ls.NguoiThucHien) AS TenDangNhap
        FROM LichSuThayDoi ls
        LEFT JOIN TaiKhoan tk 
            ON TRY_CAST(ls.NguoiThucHien AS INT) = tk.MaTK
    """

    filters = []
    params = []

    # --- Lọc theo bảng ---
    if selected_table:
        filters.append("ls.TenBang = ?")
        params.append(selected_table)

    # --- Lọc theo hành động ---
    if selected_action:
        filters.append("ls.HanhDong = ?")
        params.append(selected_action)

    # --- Lọc theo người thực hiện (LIKE) ---
    if keyword_user:
        filters.append("(tk.TenDangNhap LIKE ? OR ls.NguoiThucHien LIKE ?)")
        like_pattern = f"%{keyword_user}%"
        params.extend([like_pattern, like_pattern])

    if filters:
        base_query += " WHERE " + " AND ".join(filters)

    base_query += " ORDER BY ls.ThoiGian DESC"

    # --- Truy vấn dữ liệu lịch sử ---
    try:
        cursor.execute(base_query, params)
        rows = cursor.fetchall()

        # --- Danh sách bảng và hành động (thêm “Xem chi tiết”) ---
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
        flash(f"❌ Lỗi khi tải lịch sử thay đổi: {e}", "danger")
        rows, table_names, action_names = [], [], []

    finally:
        conn.close()

    return render_template(
        "history.html",
        histories=rows,
        tables=table_names,
        actions=action_names,
        selected_table=selected_table,
        selected_action=selected_action,
        keyword_user=keyword_user
    )
