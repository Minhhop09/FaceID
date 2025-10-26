from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from core.db_utils import get_sql_connection
from core.decorators import require_role
from datetime import datetime, time

shift_bp = Blueprint("shift_bp", __name__)

# ============================================================
# 🕒 DANH SÁCH CA LÀM VIỆC
# ============================================================
@shift_bp.route("/shifts")
@require_role("admin", "hr", "quanlyphongban")
def shifts():
    keyword = request.args.get("q", "").strip().lower()
    role = session.get("role", "admin")

    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🟢 Lấy danh sách ca đang hoạt động
    cursor.execute("""
        SELECT MaCa, TenCa, GioBatDau, GioKetThuc, HeSo, MoTa
        FROM CaLamViec
        WHERE TrangThai = 1
        ORDER BY MaCa
    """)
    rows = cursor.fetchall()

    shifts = []
    for row in rows:
        ma_ca, ten_ca, gio_bd, gio_kt, he_so, mo_ta = row

        def fmt(t):
            try:
                if isinstance(t, str):
                    return t[:5]
                return t.strftime("%H:%M")
            except Exception:
                return str(t)

        gio_bd_fmt = fmt(gio_bd)
        gio_kt_fmt = fmt(gio_kt)
        now_time = datetime.now().strftime("%H:%M")

        trang_thai = "Đang hoạt động" if gio_bd_fmt <= now_time <= gio_kt_fmt else "Ngoài giờ"

        shifts.append({
            "MaCa": ma_ca,
            "TenCa": ten_ca,
            "GioBatDau": gio_bd_fmt,
            "GioKetThuc": gio_kt_fmt,
            "HeSoLuong": he_so,
            "MoTa": mo_ta,
            "TrangThai": trang_thai,
            "ThoiGian": f"{gio_bd_fmt} - {gio_kt_fmt}",
            "LastUpdated": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        })

    # 🔍 Tìm kiếm
    if keyword:
        shifts = [
            s for s in shifts
            if keyword in s["TenCa"].lower() or keyword in s["MaCa"].lower()
        ]

    # 📊 Thống kê tổng quan
    cursor.execute("SELECT COUNT(*) FROM CaLamViec WHERE TrangThai = 1")
    total_shifts = cursor.fetchone()[0]

    active_shifts = sum(1 for s in shifts if s["TrangThai"] == "Đang hoạt động")

    cursor.execute("SELECT COUNT(DISTINCT MaNV) FROM LichLamViec WHERE DaXoa = 1")
    total_assigned = cursor.fetchone()[0]

    conn.close()

    # 🔹 Render theo vai trò
    if role == "hr":
        template_name = "hr_shifts.html"
    elif role == "quanlyphongban":
        template_name = "qlpb_shifts.html"
    else:
        template_name = "shifts.html"

    return render_template(
        template_name,
        shifts=shifts,
        total_shifts=total_shifts,
        active_shifts=active_shifts,
        total_employees=total_assigned,
        keyword=keyword,
        role=role
    )


# ============================================================
# 🔍 CHI TIẾT CA LÀM VIỆC
# ============================================================
@shift_bp.route("/shifts/<ma_ca>")
@require_role("admin", "hr", "quanlyphongban")
def shift_detail(ma_ca):
    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role", "admin")

    # --- Lấy thông tin ca làm ---
    cursor.execute("""
        SELECT 
            MaCa, 
            TenCa, 
            GioBatDau, 
            GioKetThuc, 
            HeSo, 
            MoTa, 
            FORMAT(NgayCapNhat, 'dd/MM/yyyy HH:mm:ss') AS NgayCapNhat
        FROM CaLamViec
        WHERE MaCa = ?
    """, (ma_ca,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("❌ Không tìm thấy ca làm việc!", "error")
        return redirect(url_for("shift_bp.shifts"))

    ma_ca, ten_ca, gio_bd, gio_kt, he_so, mo_ta, ngay_cap_nhat = row

    def fmt_time(t):
        try:
            if isinstance(t, str):
                return t[:5]
            return t.strftime("%H:%M")
        except Exception:
            return str(t)

    gio_bd_fmt = fmt_time(gio_bd)
    gio_kt_fmt = fmt_time(gio_kt)
    now_str = datetime.now().strftime("%H:%M")

    ca_info = {
        "ma_ca": ma_ca,
        "ten_ca": ten_ca,
        "gio_bd": gio_bd_fmt,
        "gio_kt": gio_kt_fmt,
        "he_so": he_so if he_so else "—",
        "mo_ta": mo_ta if mo_ta else "Không có mô tả",
        "trang_thai": "Đang hoạt động" if gio_bd_fmt <= now_str <= gio_kt_fmt else "Ngoài giờ",
        "last_updated": ngay_cap_nhat if ngay_cap_nhat else "Chưa cập nhật"
    }

    # --- Ghi log xem chi tiết ---
    try:
        username = session.get("username", "Hệ thống")
        cursor.execute("""
            INSERT INTO LichSuThayDoi 
            (TenBang, MaBanGhi, HanhDong, ThoiGian, NguoiThucHien)
            VALUES (N'CaLamViec', ?, N'Xem chi tiết', GETDATE(), ?)
        """, (ma_ca, username))
        conn.commit()
    except Exception as e:
        print("⚠️ Lỗi ghi log xem chi tiết ca làm việc:", e)

    # --- Lấy danh sách nhân viên thuộc ca ---
    keyword = request.args.get("q", "").strip()
    order = request.args.get("sort", "ten")

    query = """
        SELECT nv.MaNV, nv.HoTen, pb.TenPB, nv.ChucVu
        FROM LichLamViec llv
        JOIN NhanVien nv ON llv.MaNV = nv.MaNV
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        WHERE llv.MaCa = ? AND llv.DaXoa = 1
    """
    params = [ma_ca]

    if keyword:
        query += " AND (nv.HoTen LIKE ? OR nv.MaNV LIKE ? OR pb.TenPB LIKE ?)"
        params.extend([f"%{keyword}%"] * 3)

    if order == "ten":
        query += " ORDER BY nv.HoTen"
    elif order == "phongban":
        query += " ORDER BY pb.TenPB"
    else:
        query += " ORDER BY nv.MaNV"

    cursor.execute(query, params)
    nhanviens = cursor.fetchall()
    conn.close()

    # --- Chọn template theo vai trò ---
    if role == "hr":
        template_name = "hr_shift_detail.html"
    elif role == "quanlyphongban":
        template_name = "qlpb_shift_detail.html"
    else:
        template_name = "shift_detail.html"

    return render_template(
        template_name,
        ca=ca_info,
        nhanviens=nhanviens,
        keyword=keyword,
        order=order,
        role=role
    )

# ============================================================
# ➕ THÊM CA LÀM VIỆC (Admin + HR)
# ============================================================
@shift_bp.route("/shifts/add", methods=["GET", "POST"])
@require_role("admin", "hr")
def add_shift():
    role = session.get("role", "admin")
    username = session.get("username", "Hệ thống")

    if request.method == "POST":
        ten_ca = request.form.get("ten_ca", "").strip()
        gio_bd = request.form.get("gio_bat_dau", "").strip()
        gio_kt = request.form.get("gio_ket_thuc", "").strip()
        he_so = request.form.get("he_so", 1.0)
        mo_ta = request.form.get("mo_ta", "").strip()

        # --- Kiểm tra hợp lệ ---
        if not ten_ca or not gio_bd or not gio_kt:
            flash("⚠️ Vui lòng nhập đầy đủ thông tin ca làm việc!", "warning")
            template_name = "hr_add_shift.html" if role == "hr" else "add_shift.html"
            return render_template(template_name, role=role)

        conn = get_sql_connection()
        cursor = conn.cursor()

        try:
            # --- Tạo mã ca mới (Ca1, Ca2, Ca3, …) ---
            cursor.execute("""
                SELECT TOP 1 MaCa 
                FROM CaLamViec 
                ORDER BY TRY_CAST(SUBSTRING(MaCa, 3, LEN(MaCa)) AS INT) DESC
            """)
            last_row = cursor.fetchone()
            if last_row and last_row[0].startswith("Ca"):
                next_num = int(''.join(filter(str.isdigit, last_row[0]))) + 1
            else:
                next_num = 1
            new_ma_ca = f"Ca{next_num}"

            # --- Thêm mới ---
            cursor.execute("""
                INSERT INTO CaLamViec (MaCa, TenCa, GioBatDau, GioKetThuc, HeSo, MoTa, TrangThai, NgayCapNhat)
                VALUES (?, ?, ?, ?, ?, ?, 1, GETDATE())
            """, (new_ma_ca, ten_ca, gio_bd, gio_kt, he_so, mo_ta))

            # --- Ghi log ---
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, N'Thêm mới', ?, ?, ?, GETDATE(), ?)
            """, ("CaLamViec", new_ma_ca, "Toàn bộ dòng", None, ten_ca, username))

            conn.commit()
            flash(f"✅ Thêm ca làm việc mới thành công! Mã ca: {new_ma_ca}", "success")
            return redirect(url_for("shift_bp.shifts"))

        except Exception as e:
            conn.rollback()
            flash(f"❌ Lỗi khi thêm ca làm việc: {e}", "danger")
        finally:
            conn.close()

    # --- Render form ---
    template_name = "hr_add_shift.html" if role == "hr" else "add_shift.html"
    return render_template(template_name, role=role)



# ============================================================
# ✏️ CHỈNH SỬA CA LÀM VIỆC (Admin + HR)
# ============================================================
@shift_bp.route("/shifts/edit/<ma_ca>", methods=["GET", "POST"])
@require_role("admin", "hr")
def edit_shift(ma_ca):
    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role", "admin")
    username = session.get("username", "Hệ thống")

    try:
        if request.method == "POST":
            ten_ca = request.form.get("ten_ca", "").strip()
            gio_bat_dau = request.form.get("gio_bat_dau", "").strip()
            gio_ket_thuc = request.form.get("gio_ket_thuc", "").strip()
            he_so = request.form.get("he_so", "").strip()

            # --- 1️⃣ Lấy dữ liệu cũ để ghi log ---
            cursor.execute("""
                SELECT TenCa, GioBatDau, GioKetThuc, HeSo
                FROM CaLamViec
                WHERE MaCa = ?
            """, (ma_ca,))
            old_data = cursor.fetchone()
            old_values = {
                "TenCa": old_data[0],
                "GioBatDau": str(old_data[1]),
                "GioKetThuc": str(old_data[2]),
                "HeSo": str(old_data[3])
            } if old_data else {}

            # --- 2️⃣ Cập nhật dữ liệu ---
            cursor.execute("""
                UPDATE CaLamViec
                SET TenCa = ?, GioBatDau = ?, GioKetThuc = ?, HeSo = ?, NgayCapNhat = GETDATE()
                WHERE MaCa = ?
            """, (ten_ca, gio_bat_dau, gio_ket_thuc, he_so, ma_ca))

            # --- 3️⃣ Ghi log các thay đổi ---
            new_values = {
                "TenCa": ten_ca,
                "GioBatDau": gio_bat_dau,
                "GioKetThuc": gio_ket_thuc,
                "HeSo": he_so
            }

            for field, new_val in new_values.items():
                old_val = old_values.get(field)
                if str(old_val) != str(new_val):
                    cursor.execute("""
                        INSERT INTO LichSuThayDoi (
                            TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                            GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                        )
                        VALUES (?, ?, N'Sửa', ?, ?, ?, GETDATE(), ?)
                    """, ('CaLamViec', ma_ca, field, old_val, new_val, username))

            conn.commit()
            flash("✅ Cập nhật ca làm việc thành công!", "success")
            return redirect(url_for("shift_bp.shifts"))

        # --- 5️⃣ GET: Lấy dữ liệu ca để hiển thị form ---
        cursor.execute("""
            SELECT 
                CLV.MaCa,
                CLV.TenCa,
                CONVERT(CHAR(5), CLV.GioBatDau, 108) AS GioBatDau,
                CONVERT(CHAR(5), CLV.GioKetThuc, 108) AS GioKetThuc,
                CLV.HeSo,
                ISNULL(CLV.MoTa, '') AS MoTa
            FROM CaLamViec CLV
            WHERE CLV.MaCa = ?
        """, (ma_ca,))
        row = cursor.fetchone()

        if not row:
            flash(f"❌ Không tìm thấy ca làm việc {ma_ca}", "error")
            return redirect(url_for("shift_bp.shifts"))

        columns = [col[0] for col in cursor.description]
        ca = dict(zip(columns, row))

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xử lý: {e}", "danger")
        ca = None
    finally:
        conn.close()

    # --- 6️⃣ Render template ---
    template_name = "hr_edit_shift.html" if role == "hr" else "edit_shift.html"
    return render_template(template_name, ca=ca, role=role)

# ============================================================
# 🗑️ XÓA MỀM CA LÀM VIỆC (Admin + HR)
# ============================================================
@shift_bp.route("/shifts/delete", methods=["POST"])
@require_role("admin", "hr")
def delete_shift():
    ma_ca_list = request.form.getlist("ma_ca")
    role = session.get("role", "admin")

    if not ma_ca_list:
        flash("⚠️ Vui lòng chọn ít nhất một ca làm việc để xóa!", "warning")
        return redirect(url_for("shift_bp.shifts"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for ma_ca in ma_ca_list:
            # 🔹 Xóa mềm ca làm việc
            cursor.execute("""
                UPDATE CaLamViec
                SET TrangThai = 0
                WHERE MaCa = ?
            """, (ma_ca,))

            # 🔹 Ghi log hành động
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, N'Xóa mềm', N'TrangThai', ?, ?, GETDATE(), ?)
            """, ("CaLamViec", ma_ca, 1, 0, username))

        conn.commit()

        if len(ma_ca_list) == 1:
            flash(f"🗑️ Đã xóa mềm ca {ma_ca_list[0]}!", "danger")
        else:
            flash(f"🗑️ Đã xóa mềm {len(ma_ca_list)} ca làm việc!", "danger")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa ca làm việc: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("shift_bp.shifts"))


# ============================================================
# 🗃️ DANH SÁCH CA LÀM VIỆC ĐÃ XÓA
# ============================================================
@shift_bp.route("/shifts/deleted")
@require_role("admin")
def deleted_shifts():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT MaCa, TenCa, GioBatDau, GioKetThuc, HeSo, MoTa, NgayCapNhat
            FROM CaLamViec
            WHERE TrangThai = 0
            ORDER BY NgayCapNhat DESC
        """)
        deleted_list = cursor.fetchall()

    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách ca đã xóa: {e}", "danger")
        deleted_list = []

    finally:
        conn.close()

    return render_template(
        "deleted_records.html",
        active_tab="shifts",
        deleted_shifts=deleted_list
    )


# ============================================================
# 🔄 KHÔI PHỤC 1 HOẶC NHIỀU CA LÀM VIỆC
# ============================================================
@shift_bp.route("/shifts/restore", methods=["POST"])
@require_role("admin")
def restore_shift():
    ma_ca_list = request.form.getlist("selected_ids")
    if not ma_ca_list:
        flash("⚠️ Chưa chọn ca nào để khôi phục!", "warning")
        return redirect(url_for("shift_bp.deleted_shifts"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for ma_ca in ma_ca_list:
            # 🔹 Khôi phục trạng thái
            cursor.execute("""
                UPDATE CaLamViec
                SET TrangThai = 1
                WHERE MaCa = ?
            """, (ma_ca,))

            # 🔹 Ghi log hành động
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, N'Khôi phục', N'TrangThai', ?, ?, GETDATE(), ?)
            """, ("CaLamViec", ma_ca, 0, 1, username))

        conn.commit()
        flash(f"✅ Đã khôi phục {len(ma_ca_list)} ca làm việc!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục ca làm việc: {e}", "danger")

    finally:
        conn.close()

    return redirect(url_for("shift_bp.deleted_shifts"))
