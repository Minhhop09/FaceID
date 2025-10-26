from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from core.db_utils import get_sql_connection
from core.decorators import require_role
from datetime import datetime

department_bp = Blueprint("department_bp", __name__)

# ============================================================
# 🏢 DANH SÁCH PHÒNG BAN
# ============================================================
@department_bp.route("/departments")
@require_role("admin", "hr", "quanlyphongban")
def departments():
    conn = get_sql_connection()
    cursor = conn.cursor()
    keyword = request.args.get("q", "").strip()
    role = session.get("role")
    username = session.get("username")

    # 🔹 Nếu là quản lý phòng ban → chuyển thẳng đến phòng ban của họ
    if role == "quanlyphongban":
        cursor.execute("""
            SELECT pb.MaPB
            FROM PhongBan pb
            JOIN NhanVien nv ON pb.QuanLyPB = nv.MaNV
            JOIN TaiKhoan tk ON nv.MaNV = tk.MaNV
            WHERE tk.TenDangNhap = ? AND pb.TrangThai = 1
        """, (username,))
        row = cursor.fetchone()
        conn.close()

        if row:
            ma_pb = row[0]
            return redirect(url_for("department_bp.department_detail", ma_pb=ma_pb))
        else:
            flash("❌ Không tìm thấy phòng ban bạn quản lý!", "error")
            return redirect(url_for("qlpb_dashboard"))

    # 🔹 Nếu là admin hoặc HR → hiển thị danh sách phòng ban
    query = """
        SELECT 
            pb.MaPB, 
            pb.TenPB, 
            nv.HoTen AS TenQuanLy, 
            pb.TrangThai, 
            COUNT(nv2.MaNV) AS SoNhanVien
        FROM PhongBan pb
        LEFT JOIN NhanVien nv ON pb.QuanLyPB = nv.MaNV
        LEFT JOIN NhanVien nv2 ON pb.MaPB = nv2.MaPB
        WHERE pb.TrangThai = 1
    """

    params = ()
    if keyword:
        query += " AND (pb.TenPB LIKE ? OR pb.MaPB LIKE ?)"
        params = (f"%{keyword}%", f"%{keyword}%")

    query += """
        GROUP BY pb.MaPB, pb.TenPB, nv.HoTen, pb.TrangThai
        ORDER BY pb.MaPB
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()

    departments = []
    for row in rows:
        ma_pb, ten_pb, ten_quan_ly, trang_thai, so_nv = row
        departments.append({
            "ma_pb": ma_pb,
            "ten_pb": ten_pb,
            "so_nv": so_nv,
            "manager": ten_quan_ly if ten_quan_ly else "Chưa có",
            "trang_thai": "Đang hoạt động",
            "last_updated": datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        })

    # 🔹 Thống kê cho admin/hr
    active_departments = total_departments = total_employees = None
    if role in ("admin", "hr"):
        cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE TrangThai = 1")
        active_departments = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE TrangThai = 1")
        total_departments = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) 
            FROM NhanVien nv
            JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            WHERE nv.TrangThai = 1 AND pb.TrangThai = 1
        """)
        total_employees = cursor.fetchone()[0]

    conn.close()

    # 🔹 Chọn template phù hợp
    template = "hr_departments.html" if role == "hr" else "departments.html"

    return render_template(
        template,
        departments=departments,
        keyword=keyword,
        total_departments=total_departments,
        total_employees=total_employees,
        active_departments=active_departments,
        role=role
    )


# ============================================================
# 🏢 CHI TIẾT PHÒNG BAN
# ============================================================
@department_bp.route("/departments/<ma_pb>")
@require_role("admin", "hr", "quanlyphongban")
def department_detail(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role")
    username = session.get("username")

    # --- Nếu là QLPB → kiểm tra quyền ---
    if role == "quanlyphongban":
        cursor.execute("""
            SELECT nv.MaNV
            FROM NhanVien nv
            JOIN TaiKhoan tk ON nv.MaNV = tk.MaNV
            WHERE tk.TenDangNhap = ?
        """, (username,))
        row = cursor.fetchone()
        ma_nv_user = row[0] if row else None

        cursor.execute("""
            SELECT QuanLyPB 
            FROM PhongBan 
            WHERE MaPB = ? AND TrangThai = 1
        """, (ma_pb,))
        phong_quan_ly = cursor.fetchone()

        if not phong_quan_ly or phong_quan_ly[0] != ma_nv_user:
            conn.close()
            flash("❌ Bạn chỉ được xem chi tiết phòng ban do mình quản lý!", "error")
            return redirect(url_for("department_bp.departments"))

    # --- Lấy thông tin phòng ban ---
    cursor.execute("""
        SELECT 
            pb.MaPB, 
            pb.TenPB, 
            nv.HoTen AS TenQuanLy, 
            pb.TrangThai, 
            pb.MoTa
        FROM PhongBan pb
        LEFT JOIN NhanVien nv ON pb.QuanLyPB = nv.MaNV
        WHERE pb.MaPB = ? AND pb.TrangThai = 1
    """, (ma_pb,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("❌ Phòng ban này không tồn tại hoặc đã ngừng hoạt động!", "error")
        return redirect(url_for("department_bp.departments"))

    ma_pb, ten_pb, ten_quan_ly, trang_thai, mo_ta = row
    pb_info = {
        "ma_pb": ma_pb,
        "ten_pb": ten_pb,
        "quan_ly": ten_quan_ly if ten_quan_ly else "Chưa có",
        "trang_thai": "Đang hoạt động",
        "mo_ta": mo_ta if mo_ta else "Không có mô tả"
    }

    # --- Ghi log xem chi tiết ---
    try:
        cursor.execute("""
            INSERT INTO LichSuThayDoi
            (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, (
            "PhongBan", ma_pb, "Xem chi tiết",
            "Toàn bộ dòng", None, pb_info["ten_pb"], username or "Hệ thống"
        ))
        conn.commit()
    except Exception as e:
        print("⚠️ Lỗi ghi log xem chi tiết phòng ban:", e)

    # --- Lấy danh sách nhân viên ---
    keyword = request.args.get("q", "").strip()
    order = request.args.get("sort", "ten")

    query = """
        SELECT MaNV, HoTen, ChucVu, NgayVaoLam
        FROM NhanVien
        WHERE MaPB = ? AND TrangThai = 1
    """
    params = [ma_pb]
    if keyword:
        query += " AND (HoTen LIKE ? OR MaNV LIKE ? OR ChucVu LIKE ?)"
        params.extend([f"%{keyword}%"] * 3)

    if order == "ten":
        query += " ORDER BY HoTen"
    elif order == "chucvu":
        query += " ORDER BY ChucVu"
    else:
        query += " ORDER BY MaNV"

    cursor.execute(query, params)
    nhanviens = cursor.fetchall()
    conn.close()

    # --- Template theo vai trò ---
    if role == "hr":
        template = "hr_department_detail.html"
    elif role == "quanlyphongban":
        template = "qlpb_department_detail.html"
    else:
        template = "department_detail.html"

    return render_template(
        template,
        pb=pb_info,
        nhanviens=nhanviens,
        keyword=keyword,
        order=order,
        role=role
    )

# ============================================================
# 🧭 PHÒNG BAN CỦA TÔI (QUẢN LÝ)
# ============================================================
@department_bp.route("/departments/my")
@require_role("quanlyphongban")
def my_department():
    ma_nv = session.get("ma_nv")
    conn = get_sql_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT MaPB FROM PhongBan WHERE QuanLyPB = ?", (ma_nv,))
    ma_pb = cursor.fetchone()
    conn.close()

    if not ma_pb:
        flash("❌ Bạn chưa được chỉ định làm quản lý phòng ban nào!", "info")
        return redirect(url_for("qlpb_dashboard"))
    return redirect(url_for("department_bp.department_detail", ma_pb=ma_pb[0]))


# ============================================================
# ➕ THÊM PHÒNG BAN
# ============================================================
@department_bp.route("/departments/add", methods=["GET", "POST"])
@require_role("admin")
def add_department():
    if request.method == "POST":
        ten_pb = request.form["ten_pb"].strip()
        mo_ta = request.form.get("mo_ta", "").strip()

        if not ten_pb:
            flash("⚠️ Tên phòng ban không được để trống!", "danger")
            return redirect(url_for("department_bp.add_department"))

        # Tạo mã viết tắt từ tên phòng ban (VD: "Công nghệ thông tin" -> "CNTT")
        words = ten_pb.split()
        ma_pb_base = "".join(w[0].upper() for w in words if w)
        ma_pb = ma_pb_base

        conn = get_sql_connection()
        cursor = conn.cursor()

        # Nếu mã trùng thì thêm số tăng dần phía sau: KD1, KD2, ...
        i = 1
        while True:
            cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE MaPB = ?", (ma_pb,))
            count = cursor.fetchone()[0]
            if count == 0:
                break
            ma_pb = f"{ma_pb_base}{i}"
            i += 1

        ngay_tao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        trang_thai = 1  # 1 = hoạt động

        cursor.execute("""
            INSERT INTO PhongBan (MaPB, TenPB, MoTa, NgayTao, TrangThai)
            VALUES (?, ?, ?, ?, ?)
        """, (ma_pb, ten_pb, mo_ta, ngay_tao, trang_thai))
        conn.commit()
        conn.close()

        flash(f"✅ Thêm phòng ban '{ten_pb}' (Mã: {ma_pb}) thành công!", "success")
        return redirect(url_for("department_bp.departments"))

    return render_template("add_department.html")


# ============================================================
# ✏️ CHỈNH SỬA PHÒNG BAN
# ============================================================
@department_bp.route("/departments/edit/<ma_pb>", methods=["GET", "POST"])
@require_role("admin")
def edit_department(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()

    # Lấy dữ liệu phòng ban cũ
    cursor.execute("SELECT MaPB, TenPB, MoTa, TrangThai FROM PhongBan WHERE MaPB = ?", (ma_pb,))
    department = cursor.fetchone()

    if not department:
        flash("❌ Không tìm thấy phòng ban!", "danger")
        conn.close()
        return redirect(url_for("department_bp.departments"))

    old_ma_pb, old_ten_pb, old_mo_ta, old_trang_thai = department

    if request.method == "POST":
        ten_pb = request.form["ten_pb"].strip()
        mo_ta = request.form["mo_ta"].strip()
        trang_thai = 1 if request.form.get("trang_thai") == "on" else 0

        # Hàm tạo mã viết tắt
        def tao_ma_viet_tat(ten):
            parts = ten.strip().split()
            if len(parts) == 1:
                return parts[0][:2].upper()
            else:
                return "".join(word[0].upper() for word in parts)

        new_ma_pb = tao_ma_viet_tat(ten_pb)

        try:
            # Nếu không đổi tên phòng ban
            if ten_pb == old_ten_pb:
                cursor.execute("""
                    UPDATE PhongBan
                    SET MoTa = ?, TrangThai = ?
                    WHERE MaPB = ?
                """, (mo_ta, trang_thai, old_ma_pb))
                conn.commit()
                flash("✅ Cập nhật mô tả phòng ban thành công!", "success")

            else:
                # Kiểm tra trùng mã phòng ban
                cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE MaPB = ?", (new_ma_pb,))
                if cursor.fetchone()[0] > 0:
                    flash(f"⚠️ Mã phòng ban '{new_ma_pb}' đã tồn tại!", "danger")
                    conn.close()
                    return redirect(url_for("department_bp.departments"))

                # Thêm bản ghi mới (vì đổi mã)
                cursor.execute("""
                    INSERT INTO PhongBan (MaPB, TenPB, MoTa, TrangThai)
                    VALUES (?, ?, ?, ?)
                """, (new_ma_pb, ten_pb, mo_ta, trang_thai))

                # Lấy danh sách nhân viên thuộc phòng ban cũ
                cursor.execute("SELECT MaNV FROM NhanVien WHERE MaPB = ?", (old_ma_pb,))
                old_nv_list = [row[0] for row in cursor.fetchall()]

                # 🚫 Tắt tạm thời ràng buộc khóa ngoại
                fk_disable = [
                    "ALTER TABLE TaiKhoan NOCHECK CONSTRAINT FK_TaiKhoan_NhanVien",
                    "ALTER TABLE KhuonMat NOCHECK CONSTRAINT FK__KhuonMat__MaNV__4222D4EF",
                    "ALTER TABLE ChamCong NOCHECK CONSTRAINT FK__ChamCong__MaNV__4F7CD00D",
                    "ALTER TABLE LichLamViec NOCHECK CONSTRAINT FK__LichLamVie__MaNV__4AB81AF0"
                ]
                for cmd in fk_disable:
                    cursor.execute(cmd)

                # Cập nhật mã nhân viên & các bảng liên quan
                for old_nv in old_nv_list:
                    so_thu_tu = ''.join(ch for ch in old_nv if ch.isdigit())
                    new_nv = f"NV{new_ma_pb}{so_thu_tu}"

                    cursor.execute("""
                        UPDATE NhanVien
                        SET MaNV=?, MaPB=?
                        WHERE MaNV=?
                    """, (new_nv, new_ma_pb, old_nv))

                    cursor.execute("""
                        UPDATE TaiKhoan
                        SET MaNV=?, TenDangNhap=?
                        WHERE MaNV=? AND VaiTro='nhanvien'
                    """, (new_nv, new_nv, old_nv))

                    cursor.execute("""
                        UPDATE KhuonMat SET MaNV=? WHERE MaNV=?
                    """, (new_nv, old_nv))

                    cursor.execute("""
                        UPDATE ChamCong SET MaNV=? WHERE MaNV=?
                    """, (new_nv, old_nv))

                    cursor.execute("""
                        UPDATE LichLamViec SET MaNV=? WHERE MaNV=?
                    """, (new_nv, old_nv))

                # ✅ Bật lại FK
                fk_enable = [
                    "ALTER TABLE TaiKhoan WITH CHECK CHECK CONSTRAINT FK_TaiKhoan_NhanVien",
                    "ALTER TABLE KhuonMat WITH CHECK CHECK CONSTRAINT FK__KhuonMat__MaNV__4222D4EF",
                    "ALTER TABLE ChamCong WITH CHECK CHECK CONSTRAINT FK__ChamCong__MaNV__4F7CD00D",
                    "ALTER TABLE LichLamViec WITH CHECK CHECK CONSTRAINT FK__LichLamVie__MaNV__4AB81AF0"
                ]
                for cmd in fk_enable:
                    cursor.execute(cmd)

                # Xóa phòng ban cũ
                cursor.execute("DELETE FROM PhongBan WHERE MaPB = ?", (old_ma_pb,))
                conn.commit()

                flash(f"✅ Đã đổi '{old_ten_pb}' → '{ten_pb}' (mã mới: {new_ma_pb}) và đồng bộ toàn bộ dữ liệu thành công!", "success")

        except Exception as e:
            conn.rollback()
            flash(f"❌ Lỗi khi cập nhật phòng ban: {e}", "danger")

        finally:
            conn.close()

        return redirect(url_for("department_bp.departments"))

    conn.close()
    return render_template("edit_department.html", department=department)

# ============================================================
# 🗑 XÓA MỀM 1 PHÒNG BAN
# ============================================================
@department_bp.route("/departments/delete/<string:ma_pb>", methods=["POST"])
@require_role("admin")
def delete_department(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT TenPB, TrangThai FROM PhongBan WHERE MaPB = ?", (ma_pb,))
        row = cursor.fetchone()
        if not row:
            flash("❌ Không tìm thấy phòng ban để xóa!", "danger")
            return redirect(url_for("department_bp.departments"))

        old_name, old_status = row

        cursor.execute("""
            UPDATE PhongBan
            SET TrangThai = 0
            WHERE MaPB = ?
        """, (ma_pb,))

        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, (
            "PhongBan",
            ma_pb,
            "Xóa mềm",
            "TrangThai",
            old_status,
            0,
            session.get("username", "Hệ thống")
        ))

        conn.commit()
        flash(f"🗑 Đã xóa mềm phòng ban {old_name} ({ma_pb}).", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa mềm phòng ban: {str(e)}", "danger")

    finally:
        conn.close()

    return redirect(url_for("department_bp.departments"))


# ============================================================
# 🗑 XÓA MỀM NHIỀU PHÒNG BAN
# ============================================================
@department_bp.route("/departments/delete-multiple", methods=["POST"])
@require_role("admin")
def delete_multiple_departments():
    selected_ids = request.form.getlist("selected_departments")

    if not selected_ids:
        flash("⚠️ Bạn chưa chọn phòng ban nào để xóa!", "warning")
        return redirect(url_for("department_bp.departments"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for ma_pb in selected_ids:
            cursor.execute("SELECT TenPB, TrangThai FROM PhongBan WHERE MaPB = ?", (ma_pb,))
            row = cursor.fetchone()
            if not row:
                continue

            old_name, old_status = row

            cursor.execute("""
                UPDATE PhongBan
                SET TrangThai = 0
                WHERE MaPB = ?
            """, (ma_pb,))

            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "PhongBan",
                ma_pb,
                "Xóa mềm nhiều",
                "TrangThai",
                old_status,
                0,
                username
            ))

        conn.commit()
        flash(f"🗑 Đã xóa mềm {len(selected_ids)} phòng ban thành công.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa nhiều phòng ban: {str(e)}", "danger")

    finally:
        conn.close()

    return redirect(url_for("department_bp.departments"))


# ============================================================
# ♻️ KHÔI PHỤC 1 PHÒNG BAN
# ============================================================
@department_bp.route("/departments/restore/<string:ma_pb>", methods=["POST"])
@require_role("admin")
def restore_department(ma_pb):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT TenPB, TrangThai FROM PhongBan WHERE MaPB = ?
        """, (ma_pb,))
        row = cursor.fetchone()

        if not row:
            flash("❌ Không tìm thấy phòng ban cần khôi phục!", "danger")
            return redirect(url_for("department_bp.deleted_departments_list"))

        ten_pb, trang_thai = row
        if trang_thai == 1:
            flash(f"⚠️ Phòng ban {ten_pb} ({ma_pb}) đang hoạt động, không cần khôi phục.", "warning")
            return redirect(url_for("department_bp.deleted_departments_list"))

        cursor.execute("""
            UPDATE PhongBan SET TrangThai = 1 WHERE MaPB = ?
        """, (ma_pb,))

        username = session.get("username", "Hệ thống")
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, (
            "PhongBan", ma_pb, "Khôi phục", "TrangThai",
            trang_thai, 1, username
        ))

        conn.commit()
        flash(f"♻️ Đã khôi phục phòng ban {ten_pb} ({ma_pb}) thành công.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục phòng ban: {str(e)}", "danger")

    finally:
        conn.close()

    return redirect(url_for("department_bp.deleted_departments_list"))


# ============================================================
# ♻️ KHÔI PHỤC NHIỀU PHÒNG BAN
# ============================================================
@department_bp.route("/departments/restore-multiple", methods=["POST"])
@require_role("admin")
def restore_multiple_departments():
    selected_ids = request.form.getlist("selected_departments")

    if not selected_ids:
        flash("⚠️ Chưa chọn phòng ban nào để khôi phục!", "warning")
        return redirect(url_for("department_bp.deleted_departments_list"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        for ma_pb in selected_ids:
            cursor.execute("""
                UPDATE PhongBan SET TrangThai = 1 WHERE MaPB = ?
            """, (ma_pb,))
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "PhongBan", ma_pb, "Khôi phục nhiều", "TrangThai",
                0, 1, username
            ))

        conn.commit()
        flash(f"♻️ Đã khôi phục {len(selected_ids)} phòng ban thành công.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục nhiều phòng ban: {str(e)}", "danger")

    finally:
        conn.close()

    return redirect(url_for("department_bp.deleted_departments_list"))


# ============================================================
# 🗃 DANH SÁCH PHÒNG BAN & NHÂN VIÊN ĐÃ XÓA
# ============================================================
@department_bp.route("/departments/deleted")
@require_role("admin")
def deleted_departments_list():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                pb.MaPB, pb.TenPB, ql.HoTen AS TenQuanLy, pb.NgayTao
            FROM PhongBan pb
            LEFT JOIN NhanVien ql ON pb.QuanLyPB = ql.MaNV
            WHERE pb.TrangThai = 0
            ORDER BY pb.NgayTao DESC
        """)
        deleted_departments = cursor.fetchall()

        cursor.execute("""
            SELECT 
                nv.MaNV, nv.HoTen, nv.Email, nv.SDT, nv.ChucVu, pb.TenPB,
                nv.NgayCapNhat, ql.HoTen AS TenQuanLy
            FROM NhanVien nv
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            LEFT JOIN NhanVien ql ON pb.QuanLyPB = ql.MaNV
            WHERE nv.TrangThai = 0
            ORDER BY nv.NgayCapNhat DESC
        """)
        deleted_employees = cursor.fetchall()

    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách đã xóa: {str(e)}", "danger")
        deleted_departments, deleted_employees = [], []

    finally:
        conn.close()

    return render_template(
        "deleted_records.html",
        deleted_employees=deleted_employees,
        deleted_departments=deleted_departments,
        active_tab="departments"
    )
