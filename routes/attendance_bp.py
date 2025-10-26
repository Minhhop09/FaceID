# attendance_bp.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from core.db_utils import get_sql_connection
from core.decorators import require_role

attendance_bp = Blueprint("attendance_bp", __name__)

# BÁO CÁO CHẤM CÔNG

@attendance_bp.route("/attendance_report", methods=["GET"])
@require_role("admin", "hr", "quanlyphongban")
def attendance_report():
    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role")
    username = session.get("username")

    # --- Lọc theo tháng / năm ---
    month = request.args.get("month")
    year = request.args.get("year")

    filter_query = "WHERE CC.DaXoa = 1"
    params = []

    if month and year:
        filter_query += " AND MONTH(CC.NgayChamCong)=? AND YEAR(CC.NgayChamCong)=?"
        params.extend([month, year])
    elif year:
        filter_query += " AND YEAR(CC.NgayChamCong)=?"
        params.append(year)

    # --- Nếu là quản lý phòng ban → chỉ xem nhân viên phòng mình ---
    if role == "quanlyphongban":
        cursor.execute("""
            SELECT nv.MaPB
            FROM NhanVien nv
            JOIN TaiKhoan tk ON nv.MaNV = tk.MaNV
            WHERE tk.TenDangNhap = ?
        """, (username,))
        row = cursor.fetchone()
        ma_pb_user = row[0] if row else None
        if ma_pb_user:
            filter_query += " AND PB.MaPB = ?"
            params.append(ma_pb_user)

    # --- Lấy dữ liệu ---
    cursor.execute(f"""
        SELECT 
            CC.MaChamCong,
            NV.MaNV,
            NV.HoTen,
            PB.TenPB AS PhongBan,
            FORMAT(CC.NgayChamCong, 'yyyy-MM-dd') AS NgayChamCong,
            FORMAT(CC.GioVao, 'HH:mm') AS GioVao,
            FORMAT(CC.GioRa, 'HH:mm') AS GioRa,
            CLV.TenCa AS CaLam,
            COALESCE(CC.GioBatDauThucTe, CLV.GioBatDau) AS GioBatDauDung,
            COALESCE(CC.GioKetThucThucTe, CLV.GioKetThuc) AS GioKetThucDung,
            CASE 
                WHEN CC.GioRa IS NOT NULL 
                    THEN ROUND(DATEDIFF(MINUTE, CC.GioVao, CC.GioRa) / 60.0, 2)
                ELSE 0
            END AS SoGioLam,
            CASE 
                WHEN CC.GioVao IS NULL THEN N'Vắng'
                WHEN COALESCE(CC.GioBatDauThucTe, CLV.GioBatDau) IS NULL THEN N'Không xác định'
                ELSE 
                    CASE 
                        WHEN CAST(CC.GioVao AS TIME) > CAST(COALESCE(CC.GioBatDauThucTe, CLV.GioBatDau) AS TIME) 
                            THEN N'Đi muộn'
                        ELSE N'Đúng giờ'
                    END
            END AS TrangThaiText
        FROM ChamCong CC
        LEFT JOIN NhanVien NV ON CC.MaNV = NV.MaNV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        LEFT JOIN CaLamViec CLV ON CC.MaCa = CLV.MaCa
        {filter_query}
        ORDER BY CC.NgayChamCong DESC, NV.MaNV
    """, params)

    columns = [c[0] for c in cursor.description]
    records = [dict(zip(columns, row)) for row in cursor.fetchall()]

    # --- Thống kê ---
    total_records = len(records)
    total_on_time = sum(1 for r in records if r["TrangThaiText"] == "Đúng giờ")
    total_late = sum(1 for r in records if r["TrangThaiText"] == "Đi muộn")
    total_absent = sum(1 for r in records if r["TrangThaiText"] == "Vắng")
    attendance_rate = (total_on_time / total_records * 100) if total_records else 0
    conn.close()

    # --- Template ---
    if role == "hr":
        template_name = "hr_attendance_report.html"
    elif role == "quanlyphongban":
        template_name = "qlpb_attendance_report.html"
    else:
        template_name = "attendance_report.html"

    return render_template(
        template_name,
        records=records,
        total_records=total_records,
        total_on_time=total_on_time,
        total_late=total_late,
        total_absent=total_absent,
        attendance_rate=attendance_rate,
        month=month,
        year=year,
        role=role
    )

# THÊM CHẤM CÔNG

@attendance_bp.route("/attendance/add", methods=["GET", "POST"])
@require_role("admin", "hr")
def add_attendance():
    conn = get_sql_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        try:
            MaNV = request.form["MaNV"]
            NgayChamCong = request.form["Ngay"]
            GioVao = request.form["GioVao"]
            GioRa = request.form.get("GioRa")
            TrangThai = int(request.form["TrangThai"])

            cursor.execute("""
                INSERT INTO ChamCong (MaNV, NgayChamCong, GioVao, GioRa, TrangThai)
                VALUES (?, ?, ?, ?, ?)
            """, (MaNV, NgayChamCong, GioVao, GioRa, TrangThai))
            conn.commit()
            flash("Đã thêm bản ghi chấm công mới!", "success")
            return redirect(url_for("attendance_bp.attendance_report"))
        except Exception as e:
            flash(f"Lỗi khi thêm chấm công: {e}", "danger")
        finally:
            conn.close()

    cursor.execute("SELECT MaNV, HoTen FROM NhanVien WHERE TrangThai=1")
    employees = cursor.fetchall()
    conn.close()
    return render_template("attendance_add.html", employees=employees)

# SỬA CHẤM CÔNG

@attendance_bp.route("/attendance/edit/<int:id>", methods=["GET", "POST"])
@require_role("admin", "hr")
def edit_attendance(id):
    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role", "admin")

    if request.method == "POST":
        try:
            GioVao = request.form["GioVao"]
            GioRa = request.form.get("GioRa") or None
            TrangThai = int(request.form["TrangThai"])
            MaCa = request.form.get("MaCa") or None

            if not MaCa:
                cursor.execute("SELECT MaCa FROM ChamCong WHERE MaChamCong = ?", (id,))
                row_ma = cursor.fetchone()
                MaCa = row_ma[0] if row_ma else None

            if MaCa:
                cursor.execute("SELECT 1 FROM CaLamViec WHERE MaCa = ?", (MaCa,))
                if cursor.fetchone() is None:
                    flash("Mã ca không hợp lệ.", "warning")
                    conn.close()
                    return redirect(url_for("attendance_bp.edit_attendance", id=id))

            cursor.execute("""
                UPDATE ChamCong
                SET GioVao = ?, GioRa = ?, TrangThai = ?, MaCa = ?
                WHERE MaChamCong = ?
            """, (GioVao, GioRa, TrangThai, MaCa, id))
            conn.commit()
            flash("Đã cập nhật bản ghi chấm công!", "success")
            conn.close()
            return redirect(url_for("attendance_bp.attendance_report"))
        except Exception as e:
            conn.rollback()
            flash(f"Lỗi khi cập nhật: {e}", "danger")
            conn.close()
            return redirect(url_for("attendance_bp.attendance_report"))

    cursor.execute("""
        SELECT 
            CC.MaChamCong, CC.MaNV, NV.HoTen, PB.TenPB,
            CC.NgayChamCong, CC.GioVao, CC.GioRa, CC.TrangThai,
            CC.MaCa,
            KM.DuongDanAnh,
            CASE 
                WHEN DATEPART(HOUR, CC.GioVao) BETWEEN 5 AND 11 THEN N'Ca sáng'
                WHEN DATEPART(HOUR, CC.GioVao) BETWEEN 11 AND 17 THEN N'Ca chiều'
                WHEN DATEPART(HOUR, CC.GioVao) BETWEEN 17 AND 23 THEN N'Ca tối'
                ELSE N'Không xác định'
            END AS CaLamNhanh
        FROM ChamCong CC
        LEFT JOIN NhanVien NV ON CC.MaNV = NV.MaNV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        LEFT JOIN KhuonMat KM ON NV.MaNV = KM.MaNV
        WHERE CC.MaChamCong = ?
    """, (id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("Không tìm thấy bản ghi chấm công.", "danger")
        return redirect(url_for("attendance_bp.attendance_report"))

    cursor.execute("""
        SELECT MaCa, TenCa, 
               FORMAT(GioBatDau, 'HH:mm') + N' - ' + FORMAT(GioKetThuc, 'HH:mm') AS KhungGio
        FROM CaLamViec
        WHERE TrangThai = 1
        ORDER BY MaCa
    """)
    shifts = cursor.fetchall()
    conn.close()

    record_cols = [
        "MaChamCong","MaNV","HoTen","TenPB",
        "NgayChamCong","GioVao","GioRa","TrangThai",
        "MaCa","DuongDanAnh","CaLamNhanh"
    ]
    record = dict(zip(record_cols, row))

    avatar_path = record.get("DuongDanAnh")
    record["Avatar"] = "/" + avatar_path.replace("\\", "/") if (avatar_path and avatar_path.strip()) else "/static/photos/default.jpg"
    shift_list = [{"MaCa": s[0], "TenCa": s[1], "KhungGio": s[2]} for s in shifts]

    template_name = "hr_attendance_edit.html" if role == "hr" else "attendance_edit.html"
    return render_template(template_name, record=record, shifts=shift_list)

# XÓA MỀM 1 BẢN GHI CHẤM CÔNG

@attendance_bp.route("/attendance/delete/<int:id>", methods=["POST"])
@require_role("admin", "hr")
def delete_attendance(id):
    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role", "admin")
    username = session.get("username", "Hệ thống")

    try:
        cursor.execute("UPDATE ChamCong SET DaXoa = 0 WHERE MaChamCong = ?", (id,))
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("ChamCong", id, "Xóa mềm", "DaXoa", "1", "0", username))

        conn.commit()
        flash("Đã xóa mềm bản ghi chấm công và ghi vào lịch sử!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Lỗi khi xóa mềm bản ghi chấm công: {e}", "danger")
    finally:
        conn.close()

    if role == "hr":
        return redirect(url_for("attendance_bp.attendance_report"))
    else:
        return redirect(url_for("attendance_bp.attendance_report"))

# XÓA MỀM NHIỀU BẢN GHI CHẤM CÔNG

@attendance_bp.route("/attendance/delete_multiple", methods=["POST"])
@require_role("admin", "hr")
def delete_multiple_attendance():
    selected_ids = request.form.getlist("selected_attendance")
    if not selected_ids:
        flash("Chưa chọn bản ghi chấm công nào để xóa!", "warning")
        return redirect(url_for("attendance_bp.attendance_report"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role", "admin")
    username = session.get("username", "Hệ thống")

    try:
        for ma_cc in selected_ids:
            cursor.execute("UPDATE ChamCong SET DaXoa = 0 WHERE MaChamCong = ?", (ma_cc,))
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, ("ChamCong", ma_cc, "Xóa mềm", "DaXoa", "1", "0", username))

        conn.commit()
        flash(f"Đã xóa mềm {len(selected_ids)} bản ghi chấm công!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Lỗi khi xóa nhiều bản ghi chấm công: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("attendance_bp.attendance_report"))

# KHÔI PHỤC 1 BẢN GHI CHẤM CÔNG

@attendance_bp.route("/attendance/restore/<int:id>", methods=["POST"])
@require_role("admin")
def restore_attendance(id):
    conn = get_sql_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE ChamCong SET DaXoa = 1 WHERE MaChamCong = ?", (id,))
        conn.commit()
        flash("Đã khôi phục bản ghi chấm công!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Lỗi khi khôi phục: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("attendance_bp.deleted_attendance"))

# KHÔI PHỤC NHIỀU BẢN GHI CHẤM CÔNG

@attendance_bp.route("/attendance/restore_multiple", methods=["POST"])
@require_role("admin")
def restore_multiple_attendance():
    selected_ids = request.form.getlist("selected_ids")

    if not selected_ids:
        flash("Chưa chọn bản ghi nào để khôi phục!", "warning")
        return redirect(url_for("attendance_bp.deleted_attendance"))

    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        username = session.get("username", "Hệ thống")
        for ma_cc in selected_ids:
            cursor.execute("UPDATE ChamCong SET DaXoa = 1 WHERE MaChamCong = ?", (ma_cc,))
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, ("ChamCong", ma_cc, "Khôi phục", "DaXoa", "0", "1", username))

        conn.commit()
        flash(f"Đã khôi phục {len(selected_ids)} bản ghi chấm công!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Lỗi khi khôi phục: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("attendance_bp.deleted_attendance"))

# DANH SÁCH CHẤM CÔNG ĐÃ XÓA

@attendance_bp.route("/attendance/deleted")
@require_role("admin")
def deleted_attendance():
    from datetime import datetime, time
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
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
            return val.replace("1900-01-01", "").strip() or "—"

        deleted_attendance = []
        for ma_cham_cong, ma_nv, ho_ten, ten_pb, ten_ca, ngay, gio_vao, gio_ra, trang_thai in rows:
            gio_vao_txt, gio_ra_txt = format_time(gio_vao), format_time(gio_ra)
            trang_thai = int(trang_thai or 0)
            if trang_thai == 1:
                status_text, status_class = "Đúng giờ", "bg-success"
            elif trang_thai == 2:
                status_text, status_class = "Đi muộn", "bg-warning text-dark"
            elif trang_thai == 0:
                status_text, status_class = "Vắng", "bg-danger"
            else:
                status_text, status_class = "Không xác định", "bg-secondary"

            deleted_attendance.append({
                "MaChamCong": str(ma_cham_cong),
                "MaNV": str(ma_nv) if ma_nv else "—",
                "HoTen": ho_ten or "—",
                "TenPB": ten_pb or "—",
                "TenCa": ten_ca or "—",
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

    except Exception as e:
        flash(f"Lỗi khi tải danh sách chấm công đã xóa: {e}", "error")
        deleted_attendance = []
    finally:
        conn.close()

    return render_template(
        "deleted_records.html",
        active_tab="attendance",
        deleted_attendance=deleted_attendance
    )
