from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session
from datetime import datetime
from core.db_utils import get_sql_connection, get_connection
from core.decorators import require_role

schedule_bp = Blueprint("schedule_bp", __name__)
# ============================================================
# 👥 DANH SÁCH NHÂN VIÊN ĐÃ PHÂN CA — FINAL FIXED v4 (Chuẩn xác & Hiển thị phép đúng)

# ============================================================
# 👥 DANH SÁCH NHÂN VIÊN ĐÃ PHÂN CA — FINAL FIXED v6 (Chuẩn xác nhất)
# ============================================================
@schedule_bp.route("/assigned_employees")
@require_role("admin", "hr", "quanlyphongban")
def assigned_employees():
    """
    ✅ DANH SÁCH PHÂN CA — FINAL FIXED
    - Trạng thái chuẩn:
        0: Vắng mặt
        1: Đúng giờ
        2: Đi muộn
        3: Nghỉ phép
        4: Chưa chấm (dành cho ca tương lai)
    - Nếu có giờ vào nhưng chưa có trạng thái → tự xác định (dựa theo giờ vào).
    """
    from datetime import datetime
    conn = get_connection()
    cursor = conn.cursor()

    # ============================================================
    # 1️⃣ ĐÁNH DẤU VẮNG (CA ĐÃ QUA KHÔNG CHẤM & KHÔNG PHÉP)
    # ============================================================
    cursor.execute("""
        UPDATE llv
        SET llv.TrangThai = 0
        FROM LichLamViec llv
        LEFT JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
        WHERE llv.DaXoa = 1
          AND (
                llv.NgayLam < CAST(GETDATE() AS DATE)
                OR (llv.NgayLam = CAST(GETDATE() AS DATE)
                    AND CONVERT(TIME, GETDATE()) > clv.GioKetThuc)
              )
          AND llv.TrangThai NOT IN (1, 2, 3)
          AND NOT EXISTS (
                SELECT 1 FROM ChamCong cc
                WHERE cc.MaNV = llv.MaNV
                  AND CONVERT(date, cc.NgayChamCong) = CONVERT(date, llv.NgayLam)
                  AND cc.MaCa = llv.MaCa
                  AND cc.DaXoa = 1
              )
          AND NOT EXISTS (
                SELECT 1 FROM DonNghiPhep_CaLam dn
                JOIN DonNghiPhep d ON d.MaDon = dn.MaDon
                WHERE dn.MaCa = llv.MaCa
                  AND dn.NgayNghi = llv.NgayLam
                  AND d.MaNV = llv.MaNV
                  AND d.TrangThaiDuyet = N'Đã duyệt'
              );
    """)
    conn.commit()

    # ============================================================
    # 2️⃣ LẤY VAI TRÒ NGƯỜI DÙNG
    # ============================================================
    role = session.get("role")
    username = session.get("username")
    ma_pb_user = None

    if role == "quanlyphongban":
        cursor.execute("""
            SELECT nv.MaPB
            FROM NhanVien nv
            JOIN TaiKhoan tk ON nv.MaNV = tk.MaNV
            WHERE tk.TenDangNhap = ?
        """, (username,))
        row = cursor.fetchone()
        ma_pb_user = row[0] if row else None

    # ============================================================
    # 3️⃣ TRUY VẤN CHÍNH — GHÉP LỊCH + CHẤM CÔNG
    # ============================================================
    base_query = """
        SELECT 
            llv.MaLLV,
            nv.MaNV,
            nv.HoTen,
            pb.TenPB,
            clv.TenCa,
            CONVERT(VARCHAR(5), clv.GioBatDau, 108) AS GioBatDau,
            CONVERT(VARCHAR(5), clv.GioKetThuc, 108) AS GioKetThuc,
            FORMAT(cc.GioVao, 'HH:mm') AS GioVao,
            FORMAT(cc.GioRa, 'HH:mm') AS GioRa,
            llv.NgayLam,

            -- ✅ XÁC ĐỊNH TRẠNG THÁI CHUẨN
            CASE
                WHEN cc.TrangThai = 3 OR llv.TrangThai = 3 THEN 3   -- Nghỉ phép
                WHEN cc.TrangThai = 2 THEN 2                        -- Đi muộn
                WHEN cc.TrangThai = 1 THEN 1                        -- Đúng giờ
                WHEN cc.TrangThai IS NULL AND cc.GioVao IS NOT NULL THEN
                    CASE 
                        WHEN TRY_CONVERT(TIME, cc.GioVao) > clv.GioBatDau THEN 2
                        ELSE 1
                    END
                WHEN llv.NgayLam > CAST(GETDATE() AS DATE) THEN 4   -- Chưa chấm (ca tương lai)
                ELSE 0                                               -- Vắng
            END AS TrangThai,

            -- ✅ DIỄN GIẢI
            CASE
                WHEN cc.TrangThai = 3 OR llv.TrangThai = 3 THEN N'Nghỉ phép'
                WHEN cc.TrangThai = 2 THEN N'Đi muộn'
                WHEN cc.TrangThai = 1 THEN N'Đúng giờ'
                WHEN cc.TrangThai IS NULL AND cc.GioVao IS NOT NULL THEN
                    CASE 
                        WHEN TRY_CONVERT(TIME, cc.GioVao) > clv.GioBatDau THEN N'Đi muộn'
                        ELSE N'Đúng giờ'
                    END
                WHEN llv.NgayLam > CAST(GETDATE() AS DATE) THEN N'Chưa chấm'
                ELSE N'Vắng mặt'
            END AS TrangThaiText

        FROM LichLamViec llv
        LEFT JOIN NhanVien nv  ON llv.MaNV = nv.MaNV
        LEFT JOIN PhongBan pb  ON nv.MaPB   = pb.MaPB
        LEFT JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
        OUTER APPLY (
            SELECT TOP 1 c.GioVao, c.GioRa, c.TrangThai
            FROM ChamCong c
            WHERE c.MaNV = llv.MaNV
              AND CONVERT(date, c.NgayChamCong) = CONVERT(date, llv.NgayLam)
              AND (c.MaCa = llv.MaCa OR c.MaCa IS NULL)
              AND c.DaXoa = 1
            ORDER BY c.MaChamCong DESC
        ) AS cc
        WHERE llv.DaXoa = 1
    """

    if role == "quanlyphongban" and ma_pb_user:
        base_query += " AND nv.MaPB = ?"
        cursor.execute(base_query + " ORDER BY llv.NgayLam DESC, nv.HoTen, clv.TenCa", (ma_pb_user,))
    else:
        cursor.execute(base_query + " ORDER BY llv.NgayLam DESC, nv.HoTen, clv.TenCa")

    # ============================================================
    # 4️⃣ CHUYỂN DỮ LIỆU VÀ ĐỊNH DẠNG
    # ============================================================
    columns = [c[0] for c in cursor.description]
    records = [dict(zip(columns, row)) for row in cursor.fetchall()]

    def fmt_time(t):
        if not t: return "-"
        try:
            if hasattr(t, "strftime"): return t.strftime("%H:%M")
            if isinstance(t, str):
                return datetime.strptime(t.strip(), "%H:%M:%S").strftime("%H:%M")
        except: pass
        return str(t)

    def fmt_date(d):
        if not d: return "-"
        try:
            if hasattr(d, "strftime"): return d.strftime("%d/%m/%Y")
            if isinstance(d, str):
                return datetime.strptime(d.strip(), "%Y-%m-%d").strftime("%d/%m/%Y")
        except: pass
        return str(d)

    for r in records:
        r["GioBatDauText"] = fmt_time(r.get("GioBatDau"))
        r["GioKetThucText"] = fmt_time(r.get("GioKetThuc"))
        r["GioVaoText"] = fmt_time(r.get("GioVao"))
        r["GioRaText"] = fmt_time(r.get("GioRa"))
        r["NgayLamText"] = fmt_date(r.get("NgayLam"))

    # ============================================================
    # 5️⃣ THỐNG KÊ
    # ============================================================
    present_count = sum(1 for r in records if r["TrangThai"] == 1)
    late_count = sum(1 for r in records if r["TrangThai"] == 2)
    leave_count = sum(1 for r in records if r["TrangThai"] == 3)
    absent_count = sum(1 for r in records if r["TrangThai"] == 0)
    unchecked_count = sum(1 for r in records if r["TrangThai"] == 4)
    total_count = len(records)

    # ============================================================
    # 6️⃣ CHỌN TEMPLATE
    # ============================================================
    template = (
        "hr_assigned_employees.html"
        if role == "hr" else
        "qlpb_assigned_employees.html"
        if role == "quanlyphongban" else
        "assigned_employees.html"
    )

    conn.close()
    return render_template(
        template,
        records=records,
        present_count=present_count,
        late_count=late_count,
        leave_count=leave_count,
        absent_count=absent_count,
        unchecked_count=unchecked_count,
        total_count=total_count,
        role=role
    )



# ============================================================
# 📅 API LỊCH PHÂN CA CỦA NHÂN VIÊN
# ============================================================
@schedule_bp.route("/api/schedule/<ma_nv>")
def api_schedule(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT CONVERT(varchar, NgayLam, 23), CLV.TenCa
        FROM LichLamViec LLV
        JOIN CaLamViec CLV ON LLV.MaCa = CLV.MaCa
        WHERE LLV.MaNV = ?
    """, (ma_nv,))
    data = [{"date": r[0], "shift": r[1]} for r in cursor.fetchall()]
    conn.close()
    return jsonify(data)


# ============================================================
# 🟦 THÊM PHÂN CA MỚI
# ============================================================
@schedule_bp.route("/assign_shift", methods=["GET", "POST"])
@require_role("admin", "hr")
def assign_shift():
    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role", "admin")

    if request.method == "POST":
        MaNV_list = request.form.getlist("MaNV[]")
        MaCa_list = request.form.getlist("MaCa[]")
        NgayLam_raw = request.form.get("NgayLam[]") or request.form.getlist("NgayLam[]")

        NgayLam_list = (
            [d.strip() for d in NgayLam_raw.split(",") if d.strip()]
            if isinstance(NgayLam_raw, str)
            else NgayLam_raw
        )

        if not MaNV_list or not MaCa_list or not NgayLam_list:
            flash("⚠️ Vui lòng chọn ít nhất 1 nhân viên, 1 ca và 1 ngày!", "warning")
            conn.close()
            return redirect(url_for("schedule_bp.assign_shift"))

        inserted, skipped = 0, 0
        for ma_nv in MaNV_list:
            for ma_ca in MaCa_list:
                for ngay in NgayLam_list:
                    cursor.execute("""
                        SELECT COUNT(*) 
                        FROM LichLamViec
                        WHERE MaNV = ? AND MaCa = ? AND NgayLam = ?
                    """, (ma_nv, ma_ca, ngay))
                    if cursor.fetchone()[0] == 0:
                        cursor.execute("""
                            INSERT INTO LichLamViec (MaNV, MaCa, NgayLam, TrangThai, DaXoa)
                            VALUES (?, ?, ?, 0, 1)
                        """, (ma_nv, ma_ca, ngay))
                        inserted += 1
                    else:
                        skipped += 1

        conn.commit()
        conn.close()
        flash(f"✅ Đã phân {inserted} ca, bỏ qua {skipped} ca trùng!", "success")
        return redirect(url_for("schedule_bp.assigned_employees"))

    # Lấy danh sách nhân viên và ca
    cursor.execute("SELECT MaNV, HoTen FROM NhanVien WHERE TrangThai = 1 ORDER BY HoTen")
    employees = cursor.fetchall()
    cursor.execute("SELECT MaCa, TenCa FROM CaLamViec WHERE TrangThai = 1 ORDER BY MaCa")
    shifts = cursor.fetchall()
    conn.close()

    template = "hr_assign_shift.html" if role == "hr" else "assign_shift.html"
    return render_template(template, employees=employees, shifts=shifts)


# ============================================================
# ✏️ SỬA PHÂN CA
# ============================================================
@schedule_bp.route("/edit_shift_assignment/<int:id>", methods=["GET", "POST"])
@require_role("admin", "hr")
def edit_shift_assignment(id):
    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role", "admin")

    cursor.execute("""
        SELECT LLV.MaLLV, LLV.MaNV, LLV.MaCa, LLV.NgayLam, NV.HoTen, CLV.TenCa
        FROM LichLamViec LLV
        LEFT JOIN NhanVien NV ON NV.MaNV = LLV.MaNV
        LEFT JOIN CaLamViec CLV ON CLV.MaCa = LLV.MaCa
        WHERE LLV.MaLLV = ?
    """, (id,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("❌ Không tìm thấy phân ca cần sửa!", "danger")
        return redirect(url_for("schedule_bp.assigned_employees"))

    columns = [col[0] for col in cursor.description]
    record = dict(zip(columns, row))

    if isinstance(record.get("NgayLam"), str):
        try:
            record["NgayLam"] = datetime.strptime(record["NgayLam"], "%Y-%m-%d")
        except ValueError:
            record["NgayLam"] = None

    cursor.execute("SELECT MaNV, HoTen FROM NhanVien WHERE TrangThai = 1 ORDER BY HoTen")
    employees = cursor.fetchall()
    cursor.execute("SELECT MaCa, TenCa FROM CaLamViec WHERE TrangThai = 1 ORDER BY MaCa")
    shifts = cursor.fetchall()

    if request.method == "POST":
        MaNV = request.form.get("MaNV")
        MaCa = request.form.get("MaCa")
        NgayLam = request.form.get("NgayLam")

        if not (MaNV and MaCa and NgayLam):
            flash("⚠️ Vui lòng điền đầy đủ thông tin trước khi lưu!", "warning")
            conn.close()
            return redirect(url_for("schedule_bp.edit_shift_assignment", id=id))

        cursor.execute("""
            UPDATE LichLamViec
            SET MaNV=?, MaCa=?, NgayLam=?
            WHERE MaLLV=?
        """, (MaNV, MaCa, NgayLam, id))
        conn.commit()
        conn.close()

        flash("✅ Đã cập nhật thông tin phân ca thành công!", "success")
        return redirect(url_for("schedule_bp.assigned_employees"))

    conn.close()
    template = "hr_edit_shift_assignment.html" if role == "hr" else "edit_shift_assignment.html"
    return render_template(template, record=record, employees=employees, shifts=shifts)

# ============================================================
# 🗑️ XÓA MỀM 1 PHÂN CA
# ============================================================
@schedule_bp.route("/shift_assignments/delete/<id>")
@require_role("admin", "hr")
def delete_shift_assignment(id):
    conn = get_connection()
    cursor = conn.cursor()
    role = session.get("role", "admin")
    username = session.get("username", "Hệ thống")

    try:
        cursor.execute("SELECT DaXoa, MaNV, MaCa, NgayLam FROM LichLamViec WHERE MaLLV = ?", (id,))
        old_data = cursor.fetchone()

        if not old_data:
            flash("❌ Không tìm thấy phân ca để xóa!", "danger")
            conn.close()
            return redirect(url_for("schedule_bp.assigned_employees"))

        cursor.execute("UPDATE LichLamViec SET DaXoa = 0 WHERE MaLLV = ?", (id,))
        cursor.execute("""
            INSERT INTO LichSuThayDoi 
            (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("LichLamViec", id, "Xóa mềm", "DaXoa", str(old_data[0]), "0", username))

        conn.commit()
        flash("🗑️ Đã xóa mềm phân ca và ghi vào lịch sử!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"⚠️ Lỗi khi xóa phân ca: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("schedule_bp.assigned_employees"))


# ============================================================
# 🗑️ XÓA MỀM NHIỀU PHÂN CA
# ============================================================
@schedule_bp.route("/shift_assignments/delete", methods=["POST"])
@require_role("admin", "hr")
def delete_multiple_shift_assignments():
    selected_ids = request.form.getlist("selected_assignments")
    if not selected_ids:
        flash("⚠️ Chưa chọn phân ca nào để xóa!", "warning")
        return redirect(url_for("schedule_bp.assigned_employees"))

    conn = get_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for record_id in selected_ids:
            cursor.execute("SELECT DaXoa FROM LichLamViec WHERE MaLLV = ?", (record_id,))
            old_data = cursor.fetchone()
            if old_data:
                cursor.execute("UPDATE LichLamViec SET DaXoa = 0 WHERE MaLLV = ?", (record_id,))
                cursor.execute("""
                    INSERT INTO LichSuThayDoi 
                    (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
                    VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
                """, ("LichLamViec", record_id, "Xóa mềm", "DaXoa", str(old_data[0]), "0", username))

        conn.commit()
        flash(f"🗑️ Đã xóa mềm {len(selected_ids)} phân ca!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"⚠️ Lỗi khi xóa nhiều phân ca: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("schedule_bp.assigned_employees"))


# ============================================================
# 🔄 KHÔI PHỤC 1 PHÂN CA
# ============================================================
@schedule_bp.route("/shift_assignments/restore/<id>", methods=["POST"])
@require_role("admin")
def restore_shift_assignment(id):
    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        cursor.execute("SELECT DaXoa FROM LichLamViec WHERE MaLLV = ?", (id,))
        old_data = cursor.fetchone()

        if not old_data:
            flash("❌ Không tìm thấy phân ca để khôi phục!", "error")
            return redirect(url_for("schedule_bp.deleted_shift_assignments_list"))

        cursor.execute("UPDATE LichLamViec SET DaXoa = 1 WHERE MaLLV = ?", (id,))
        cursor.execute("""
            INSERT INTO LichSuThayDoi 
            (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("LichLamViec", id, "Khôi phục", "DaXoa", str(old_data[0]), "1", username))

        conn.commit()
        flash("✅ Đã khôi phục phân ca thành công!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"⚠️ Lỗi khi khôi phục phân ca: {e}", "error")
    finally:
        conn.close()

    return redirect(url_for("schedule_bp.deleted_shift_assignments_list"))


# ============================================================
# 🔄 KHÔI PHỤC NHIỀU PHÂN CA
# ============================================================
@schedule_bp.route("/shift_assignments/restore_multiple", methods=["POST"])
@require_role("admin")
def restore_multiple_shift_assignments():
    selected_ids = request.form.getlist("selected_assignments")
    if not selected_ids:
        flash("⚠️ Chưa chọn phân ca nào để khôi phục!", "warning")
        return redirect(url_for("schedule_bp.deleted_shift_assignments_list"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for record_id in selected_ids:
            cursor.execute("SELECT DaXoa FROM LichLamViec WHERE MaLLV = ?", (record_id,))
            old_data = cursor.fetchone()
            if old_data:
                cursor.execute("UPDATE LichLamViec SET DaXoa = 1 WHERE MaLLV = ?", (record_id,))
                cursor.execute("""
                    INSERT INTO LichSuThayDoi (
                        TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                        GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                    )
                    VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
                """, ("LichLamViec", record_id, "Khôi phục nhiều", "DaXoa", 0, 1, username))

        conn.commit()
        flash(f"✅ Đã khôi phục {len(selected_ids)} phân ca!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục nhiều phân ca: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("schedule_bp.deleted_shift_assignments_list"))


# ============================================================
# 🗃️ DANH SÁCH PHÂN CA ĐÃ XÓA MỀM
# ============================================================
@schedule_bp.route("/shift_assignments/deleted")
@require_role("admin")
def deleted_shift_assignments_list():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                llv.MaLLV,
                nv.MaNV,
                nv.HoTen,
                pb.TenPB,
                clv.TenCa,
                llv.NgayLam,
                clv.GioBatDau,
                clv.GioKetThuc,
                FORMAT(cc.GioVao, 'HH:mm') AS GioVao,
                FORMAT(cc.GioRa, 'HH:mm') AS GioRa,
                CASE 
                    WHEN cc.MaChamCong IS NOT NULL THEN 1
                    WHEN llv.TrangThai = 2 THEN 2
                    ELSE 0
                END AS TrangThai,
                CASE 
                    WHEN cc.MaChamCong IS NOT NULL THEN N'Đã chấm công'
                    WHEN llv.TrangThai = 2 THEN N'Vắng'
                    WHEN llv.TrangThai = 0 THEN N'Chưa chấm công'
                    ELSE N'Không xác định'
                END AS TrangThaiText
            FROM LichLamViec llv
            LEFT JOIN NhanVien nv ON llv.MaNV = nv.MaNV
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            LEFT JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
            OUTER APPLY (
                SELECT TOP 1 c.GioVao, c.GioRa, c.MaChamCong
                FROM ChamCong c
                WHERE c.MaNV = llv.MaNV 
                  AND c.NgayChamCong = llv.NgayLam
                  AND (c.MaCa = llv.MaCa OR c.MaCa IS NULL)
                ORDER BY 
                    CASE WHEN c.MaCa = llv.MaCa THEN 0 ELSE 1 END,
                    c.GioVao ASC
            ) AS cc
            WHERE llv.DaXoa = 0
            ORDER BY llv.NgayLam DESC, nv.HoTen
        """)
        deleted_shift_assignments = cursor.fetchall()

    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách phân ca đã xóa: {e}", "danger")
        deleted_shift_assignments = []

    finally:
        conn.close()

    return render_template(
        "deleted_records.html",
        active_tab="shift_assignments",
        deleted_shift_assignments=deleted_shift_assignments
    )
