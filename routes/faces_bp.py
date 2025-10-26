# routes/faces_bp.py
from flask import Blueprint, render_template, session, flash
from core.db_utils import get_sql_connection
from core.decorators import require_role  # hoặc import require_role từ đúng nơi bạn định nghĩa

faces_bp = Blueprint("faces_bp", __name__)

# ============================================================
# 🧠 DANH SÁCH KHUÔN MẶT ĐÃ ĐĂNG KÝ
# ============================================================
@faces_bp.route("/faces")
@require_role("admin", "hr")
def faces():
    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role", "admin")

    try:
        cursor.execute("""
            SELECT 
                k.FaceID,
                k.MaNV,
                nv.HoTen,
                pb.TenPB,
                k.DuongDanAnh,
                k.NgayDangKy,
                k.TrangThai,
                ISNULL(k.MoTa, N'Không có') AS MoTa
            FROM KhuonMat k
            JOIN NhanVien nv ON k.MaNV = nv.MaNV
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            WHERE k.TrangThai = 1       -- ✅ Chỉ lấy khuôn mặt đang hoạt động
            ORDER BY k.NgayDangKy DESC
        """)
        faces = cursor.fetchall()

    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách khuôn mặt: {e}", "danger")
        faces = []
    finally:
        conn.close()

    # 🔹 Chọn template phù hợp với vai trò
    if role == "hr":
        template_name = "hr_faces.html"
    else:
        template_name = "faces.html"

    return render_template(template_name, faces=faces, role=role)


# ============================================================
# 🧍 DANH SÁCH KHUÔN MẶT NHÂN VIÊN BỊ XÓA MỀM
# ============================================================
@faces_bp.route("/faces/deleted")
@require_role("admin")
def deleted_faces():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                k.FaceID,
                k.MaNV,
                nv.HoTen,
                pb.TenPB,
                k.DuongDanAnh,
                k.NgayDangKy,
                k.TrangThai,
                k.MoTa
            FROM KhuonMat k
            JOIN NhanVien nv ON k.MaNV = nv.MaNV
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            WHERE nv.TrangThai = 0 OR k.TrangThai = 0
            ORDER BY k.NgayDangKy DESC
        """)
        deleted_faces = cursor.fetchall()
    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách khuôn mặt bị xóa mềm: {e}", "error")
        deleted_faces = []
    finally:
        conn.close()

    return render_template("deleted_records.html", deleted_faces=deleted_faces, active_tab="faces")
