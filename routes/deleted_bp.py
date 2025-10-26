from flask import Blueprint, render_template, request, redirect, url_for, flash
from core.db_utils import get_sql_connection
from core.decorators import require_role
from datetime import datetime, time

deleted_bp = Blueprint("deleted_bp", __name__)

# ============================================================
# 🗃️ TRANG DỮ LIỆU ĐÃ XÓA (TỔNG HỢP)
# ============================================================
@deleted_bp.route("/deleted_records")
@require_role("admin")
def deleted_data():
    tab = request.args.get("tab", "employees")  # tab mặc định
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # =====================================================
        # 🧍‍♂️ NHÂN VIÊN
        # =====================================================
        if tab == "employees":
            cursor.execute("""
                SELECT nv.MaNV, nv.HoTen, nv.Email, nv.ChucVu, pb.TenPB
                FROM NhanVien nv
                LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
                WHERE nv.TrangThai = 0
            """)
            deleted_employees = cursor.fetchall()
            return render_template(
                "deleted_records.html",
                active_tab="employees",
                deleted_employees=deleted_employees
            )

        # =====================================================
        # 🏢 PHÒNG BAN
        # =====================================================
        elif tab == "departments":
            cursor.execute("""
                SELECT pb.MaPB, pb.TenPB, pb.QuanLy, 
                       (SELECT COUNT(*) FROM NhanVien WHERE MaPB = pb.MaPB) AS SoNhanVien
                FROM PhongBan pb
                WHERE pb.TrangThai = 0
            """)
            deleted_departments = cursor.fetchall()
            return render_template(
                "deleted_records.html",
                active_tab="departments",
                deleted_departments=deleted_departments
            )

        # =====================================================
        # 🔐 TÀI KHOẢN
        # =====================================================
        elif tab == "accounts":
            cursor.execute("""
                SELECT t.MaTK, t.TenDangNhap, ISNULL(n.HoTen, N'—') AS HoTen, 
                       t.VaiTro, t.NgayTao
                FROM TaiKhoan t
                LEFT JOIN NhanVien n ON t.MaNV = n.MaNV
                WHERE t.TrangThai = 0
            """)
            deleted_accounts = cursor.fetchall()
            return render_template(
                "deleted_records.html",
                active_tab="accounts",
                deleted_accounts=deleted_accounts
            )

        # =====================================================
        # 🕓 CHẤM CÔNG
        # =====================================================
        elif tab == "attendance":
            cursor.execute("""
                SELECT 
                    cc.MaChamCong,
                    ISNULL(cc.MaNV, nv.MaNV) AS MaNV,
                    nv.HoTen,
                    pb.TenPB,
                    clv.TenCa,
                    cc.NgayChamCong,
                    cc.GioVao,
                    cc.GioRa,
                    cc.TrangThai
                FROM ChamCong cc
                JOIN NhanVien nv ON cc.MaNV = nv.MaNV
                LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
                LEFT JOIN CaLamViec clv ON cc.MaCa = clv.MaCa
                WHERE cc.DaXoa = 0
                ORDER BY cc.NgayChamCong DESC
            """)
            rows = cursor.fetchall()

            def format_time(value):
                if not value:
                    return "—"
                if isinstance(value, (datetime, time)):
                    return value.strftime("%H:%M:%S")
                val = str(value)
                if " " in val:
                    val = val.split(" ")[-1]
                if "1900" in val:
                    val = val.replace("1900-01-01", "").strip()
                return val or "—"

            deleted_attendance = []
            for row in rows:
                ma_cham_cong, ma_nv, ho_ten, ten_pb, ten_ca, ngay, gio_vao, gio_ra, trang_thai = row
                gio_vao_txt = format_time(gio_vao)
                gio_ra_txt = format_time(gio_ra)
                trang_thai = int(trang_thai) if trang_thai is not None else -1
                if trang_thai == 1:
                    status_text, status_class = "Đúng giờ", "bg-success"
                elif trang_thai == 2:
                    status_text, status_class = "Đi muộn", "bg-warning text-dark"
                elif trang_thai == 0:
                    status_text, status_class = "Vắng", "bg-danger"
                else:
                    status_text, status_class = "Không xác định", "bg-secondary"

                deleted_attendance.append({
                    "MaChamCong": str(ma_cham_cong).strip(),
                    "MaNV": str(ma_nv).strip() if ma_nv else "—",
                    "HoTen": ho_ten or "",
                    "TenPB": ten_pb or "",
                    "TenCa": ten_ca or "",
                    "NgayChamCong": (
                        ngay.strftime("%Y-%m-%d") if isinstance(ngay, datetime)
                        else str(ngay)[:10] if ngay else ""
                    ),
                    "GioVao": gio_vao_txt,
                    "GioRa": gio_ra_txt,
                    "TrangThai": trang_thai,
                    "TrangThaiText": status_text,
                    "StatusClass": status_class
                })

            return render_template(
                "deleted_records.html",
                active_tab="attendance",
                deleted_attendance=deleted_attendance
            )

        # =====================================================
        # 😃 KHUÔN MẶT
        # =====================================================
        elif tab == "faces":
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
            return render_template(
                "deleted_records.html",
                active_tab="faces",
                deleted_faces=deleted_faces
            )

        # =====================================================
        # 🚨 TRƯỜNG HỢP KHÁC
        # =====================================================
        else:
            flash("⚠️ Tab không hợp lệ, đã chuyển về Nhân viên!", "warning")
            return redirect(url_for("deleted_bp.deleted_data", tab="employees"))

    except Exception as e:
        flash(f"❌ Lỗi khi tải dữ liệu đã xóa: {e}", "error")
        return redirect(url_for("admin_dashboard"))

    finally:
        conn.close()
