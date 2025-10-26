from flask import Blueprint, render_template, jsonify, session, request, redirect, url_for, flash
from datetime import datetime, date
from core.db_utils import get_sql_connection
from core.salary_utils import tinh_luong_nv, get_tham_so_luong
from core.decorators import require_role


salary_bp = Blueprint("salary_bp", __name__)

# ============================================================
# 💰 TRANG XEM LƯƠNG (Admin + HR)
# ============================================================
@salary_bp.route("/salary")
@require_role("admin", "hr")
def salary_view():
    conn = get_sql_connection()
    conn.rollback()   # ✅ reset transaction lỗi cũ
    cursor = conn.cursor()
    role = session.get("role", "admin")

    # 🔹 Xác định tháng - năm hiện tại
    today = datetime.now()
    year = today.year
    month = today.month
    print(f"[DEBUG] Xem lương cho: {year}-{month:02d}")

    # 🟢 Tổng số nhân viên đang hoạt động
    cursor.execute("SELECT COUNT(*) FROM NhanVien WHERE TrangThai = 1")
    total_employees = cursor.fetchone()[0] or 0

    # 🟢 Số nhân viên đã có lương tháng này
    cursor.execute("""
        SELECT COUNT(DISTINCT L.MaNV)
        FROM Luong L
        JOIN NhanVien NV ON L.MaNV = NV.MaNV
        WHERE YEAR(L.ThangNam) = ? 
          AND MONTH(L.ThangNam) = ?
          AND L.DaXoa = 1
          AND L.TrangThai = 1
          AND NV.TrangThai = 1
    """, (year, month))
    total_salaried = cursor.fetchone()[0] or 0

    # 🟢 Số nhân viên chưa có lương
    total_unsalaried = max(total_employees - total_salaried, 0)

    # 🟢 Tổng quỹ lương tháng này
    cursor.execute("""
        SELECT SUM(L.TongTien)
        FROM Luong L
        JOIN NhanVien NV ON L.MaNV = NV.MaNV
        WHERE YEAR(L.ThangNam) = ? 
          AND MONTH(L.ThangNam) = ?
          AND L.DaXoa = 1
          AND L.TrangThai = 1
          AND NV.TrangThai = 1
    """, (year, month))
    total_salary = cursor.fetchone()[0] or 0

    # 🟢 Danh sách chi tiết lương nhân viên
    cursor.execute("""
        SELECT 
            NV.MaNV,
            NV.HoTen,
            PB.TenPB AS PhongBan,
            ISNULL(L.SoGioLam, 0) AS SoGioLam,
            ISNULL(L.TongTien, 0) AS TongTien,
            ISNULL(L.TrangThai, 0) AS TrangThai,
            ISNULL(L.DaXoa, 1) AS DaXoa
        FROM NhanVien NV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        LEFT JOIN Luong L 
            ON NV.MaNV = L.MaNV 
            AND YEAR(L.ThangNam) = ? 
            AND MONTH(L.ThangNam) = ?
            AND (L.DaXoa = 1 OR L.DaXoa IS NULL)
        WHERE NV.TrangThai = 1
        ORDER BY NV.MaNV
    """, (year, month))

    cols = [c[0] for c in cursor.description]
    salaries = [dict(zip(cols, row)) for row in cursor.fetchall()]
    conn.close()

    template_name = "hr_salary.html" if role == "hr" else "salary.html"

    return render_template(
        template_name,
        total_employees=total_employees,
        total_salaried=total_salaried,
        total_unsalaried=total_unsalaried,
        total_salary=total_salary,
        salaries=salaries,
        current_month=f"{month:02d}",
        current_year=str(year),
        role=role
    )
# ============================================================
# 💰 TÍNH LƯƠNG TOÀN BỘ NHÂN VIÊN
# ============================================================
@salary_bp.route("/calculate_salary")
@require_role("admin", "hr")
def calculate_all_salary():
    conn = get_sql_connection()
    cursor = conn.cursor()
    nguoi_tinh = session.get("username", "Hệ thống")
    thang_nam = date.today().replace(day=1)

    try:
        cursor.execute("SELECT MaNV FROM NhanVien WHERE TrangThai = 1")
        nhanvien = cursor.fetchall()
        if not nhanvien:
            return jsonify({"success": False, "message": "⚠️ Không có nhân viên nào trong hệ thống."})

        da_tinh = 0
        loi_list = []

        for (ma_nv,) in nhanvien:
            try:
                tinh_luong_nv(cursor, ma_nv, thang_nam, nguoi_tinh, save_to_db=True, return_detail=False)
                da_tinh += 1
            except Exception as e:
                loi_list.append(f"{ma_nv}: {e}")
                print(f"[ERROR] ❌ Lỗi khi tính lương {ma_nv}: {e}")

        conn.commit()

        if loi_list:
            msg = f"⚠️ Đã tính xong {da_tinh}/{len(nhanvien)} nhân viên, nhưng có {len(loi_list)} lỗi:\n" + "\n".join(loi_list)
            return jsonify({"success": False, "message": msg})
        else:
            return jsonify({
                "success": True,
                "message": f"✅ Đã tính lương thành công cho {da_tinh}/{len(nhanvien)} nhân viên!"
            })

    except Exception as e:
        conn.rollback()
        print(f"[FATAL] ❌ Lỗi toàn hệ thống khi tính lương: {e}")
        return jsonify({
            "success": False,
            "message": f"❌ Lỗi khi tính lương toàn hệ thống: {str(e)}"
        })
    finally:
        cursor.close()
        conn.close()


# ============================================================
# 💰 TÍNH LƯƠNG CHO 1 NHÂN VIÊN
# ============================================================
@salary_bp.route("/calculate_salary/<ma_nv>")
@require_role("admin", "hr")
def calculate_salary_for_one(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()
    nguoi_tinh = session.get("username", "Hệ thống")
    thang_nam = date.today().replace(day=1)

    try:
        tong_gio, tong_tien, _ = tinh_luong_nv(
            cursor, ma_nv, thang_nam, nguoi_tinh, save_to_db=True, return_detail=True
        )
        conn.commit()
        print(f"✅ Tính lương thành công cho {ma_nv}: {tong_gio:.2f} giờ, {tong_tien:,.0f} VND")
        return jsonify({
            "success": True,
            "message": f"✅ Đã tính lương cho {ma_nv}: {tong_gio:.2f} giờ, {tong_tien:,.0f} VND"
        })
    except Exception as e:
        conn.rollback()
        print(f"[ERROR] ❌ Lỗi khi tính lương {ma_nv}: {e}")
        return jsonify({
            "success": False,
            "message": f"❌ Lỗi khi tính lương {ma_nv}: {str(e)}"
        })
    finally:
        cursor.close()
        conn.close()


# ============================================================
# 💰 XEM CHI TIẾT LƯƠNG 1 NHÂN VIÊN
# ============================================================
@salary_bp.route("/salary/<ma_nv>")
@require_role("admin", "hr")
def salary_detail(ma_nv):
    """
    Trang xem chi tiết lương của 1 nhân viên trong tháng hiện tại.
    - Gọi hàm tính lương (chỉ xem, không lưu DB)
    - Hiển thị chi tiết các ca làm việc, phụ cấp, thuế, tổng lương thực nhận
    """

    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role", "admin")
    thang_nam = date.today().replace(day=1)
    nguoi_xem = session.get("username", "Hệ thống")

    try:
        # ============================================================
        # 1️⃣ Lấy thông tin nhân viên
        # ============================================================
        cursor.execute("""
            SELECT NV.MaNV, NV.HoTen, NV.ChucVu, PB.TenPB
            FROM NhanVien NV
            LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
            WHERE NV.MaNV = ?
        """, (ma_nv,))
        emp = cursor.fetchone()
        if not emp:
            return render_template(
                "error.html",
                message=f"❌ Không tìm thấy nhân viên có mã {ma_nv}"
            )

        # ============================================================
        # 2️⃣ Gọi hàm tính lương (chỉ xem, không lưu DB)
        # ============================================================
        tong_gio, tong_tien_thuc, records = tinh_luong_nv(
            cursor,
            ma_nv,
            thang_nam,
            nguoi_xem,
            save_to_db=False,
            return_detail=True
        )

        # Nếu không có dữ liệu chấm công
        if not records:
            return render_template(
                "salary_detail.html",
                emp=emp,
                records=[],
                tong_gio=0,
                tong_tien=0,
                phu_cap=0,
                pit=0,
                tong_tien_thuc=0,
                role_label="Nhân viên",
                role_icon="fa-user text-primary",
                current_month=thang_nam.month,
                current_year=thang_nam.year,
                message="⚠️ Nhân viên này chưa có dữ liệu chấm công trong tháng."
            )

        # ============================================================
        # 3️⃣ Tính phụ cấp & thuế để hiển thị công thức tổng
        # ============================================================
        params = get_tham_so_luong(cursor)
        phu_cap_xang = params.get("PhuCapXangXe", 500000)
        phu_cap_an = params.get("PhuCapAnTrua", 30000) * len(records)
        phu_cap_khac = params.get("PhuCapKhac", 200000)
        phu_cap = phu_cap_xang + phu_cap_an + phu_cap_khac

        pit = max((tong_tien_thuc - phu_cap) * params.get("PIT_ThueThuNhap", 0.05), 0)
        tong_tien = max(tong_tien_thuc - phu_cap + pit, 0)

        # ============================================================
        # 4️⃣ Phân loại vai trò (icon + nhãn chức vụ)
        # ============================================================
        chucvu = (emp[2] or "").lower()
        if "trưởng phòng" in chucvu:
            role_label, role_icon = "Trưởng phòng", "fa-star text-warning"
        elif "phó phòng" in chucvu:
            role_label, role_icon = "Phó phòng", "fa-crown text-info"
        elif "hr" in chucvu:
            role_label, role_icon = "Nhân sự", "fa-users text-success"
        elif "thực tập" in chucvu or "intern" in chucvu:
            role_label, role_icon = "Thực tập sinh", "fa-user-graduate text-secondary"
        else:
            role_label, role_icon = "Nhân viên", "fa-user text-primary"

        # ============================================================
        # 5️⃣ Chọn template theo vai trò (HR hay Admin)
        # ============================================================
        template_name = "hr_salary_detail.html" if role == "hr" else "salary_detail.html"

        # ============================================================
        # 6️⃣ Truyền toàn bộ biến sang template
        # ============================================================
        return render_template(
            template_name,
            emp=emp,
            records=records,
            tong_gio=tong_gio or 0,
            tong_tien=tong_tien or 0,
            phu_cap=phu_cap or 0,
            pit=pit or 0,
            tong_tien_thuc=tong_tien_thuc or 0,
            role_label=role_label,
            role_icon=role_icon,
            current_month=thang_nam.month,
            current_year=thang_nam.year
        )

    except Exception as e:
        print(f"[ERROR] ❌ Lỗi khi xem chi tiết lương {ma_nv}: {e}")
        return render_template(
            "error.html",
            message=f"Lỗi khi xem chi tiết lương: {e}"
        )

    finally:
        conn.close()

# ============================================================
# ❌ XÓA MỀM 1 BẢN GHI LƯƠNG
# ============================================================
@salary_bp.route("/salary/delete/<ma_nv>", methods=["POST"])
@require_role("admin", "hr")
def delete_salary(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        cursor.execute("UPDATE Luong SET DaXoa = 0 WHERE MaNV = ?", (ma_nv,))
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("Luong", ma_nv, "Xóa mềm", "DaXoa", 1, 0, username))
        conn.commit()
        flash(f"🗑️ Đã xóa mềm lương của nhân viên {ma_nv}!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa mềm: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("salary_bp.salary_view"))

# ============================================================
# 🗑️ XÓA NHIỀU BẢN LƯƠNG
# ============================================================
@salary_bp.route("/delete_multiple_salary", methods=["POST"])
@require_role("admin", "hr")
def delete_multiple_salary():
    selected_ids = request.form.getlist("selected_ids")  # danh sách các MaLuong được chọn

    if not selected_ids:
        flash("Vui lòng chọn ít nhất một bản lương để xóa.", "warning")
        return redirect(url_for("salary_bp.salary_view"))

    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        for ma_luong in selected_ids:
            cursor.execute("UPDATE Luong SET DaXoa = 1 WHERE MaLuong = ?", (ma_luong,))
        conn.commit()
        flash(f"Đã xóa {len(selected_ids)} bản lương.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Lỗi khi xóa nhiều bản lương: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("salary_bp.salary_view"))

# ============================================================
# 📋 DANH SÁCH LƯƠNG ĐÃ XÓA
# ============================================================
@salary_bp.route("/salary/deleted")
@require_role("admin")
def deleted_salaries():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                L.MaLuong,
                NV.MaNV,
                NV.HoTen,
                PB.TenPB,
                L.SoGioLam,
                L.TongTien,
                CONVERT(varchar(7), L.ThangNam, 126) AS ThangNam   -- ✅ an toàn hơn FORMAT()
            FROM Luong L
            JOIN NhanVien NV ON L.MaNV = NV.MaNV
            LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
            WHERE L.DaXoa = 0
            ORDER BY L.ThangNam DESC
        """)
        rows = cursor.fetchall()
        cols = [c[0] for c in cursor.description]
        deleted_salaries = [dict(zip(cols, row)) for row in rows]
    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách lương đã xóa: {e}", "error")
        deleted_salaries = []
    finally:
        conn.close()

    return render_template(
        "deleted_records.html",
        deleted_salaries=deleted_salaries,
        active_tab="salary"
    )

@salary_bp.route("/salary_rules")
@require_role("admin", "hr", "manager", "employee")
def salary_rules():
    """Hiển thị trang quy tắc tính lương theo vai trò"""
    role = session.get("role", "employee")

    # 🟢 Chọn file template phù hợp
    if role == "hr":
        template_name = "hr_salary_rules.html"
    else:
        template_name = "salary_rules.html"

    return render_template(template_name)
