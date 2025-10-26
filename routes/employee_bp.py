# ============================================================
# 📄 employee_bp.py – Quản lý nhân viên
# ============================================================
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from core.db_utils import get_sql_connection
from core.decorators import require_role
from threading import Thread
from core.face_utils import async_encode_face

import os
employee_bp = Blueprint("employee_bp", __name__)

# ===========================
# Hàm encode nền (thread)
# ===========================
def async_encode_face(ma_nv, image_path):
    from core.db_utils import get_connection
    import cv2, face_recognition, time as tm

    conn = get_connection()
    cursor = conn.cursor()
    try:
        print(f"⚙️ [THREAD] Bắt đầu encode cho {ma_nv}...")
        start_encode = tm.time()

        image = face_recognition.load_image_file(image_path)
        small = cv2.resize(image, (0, 0), fx=0.25, fy=0.25)
        encodings = face_recognition.face_encodings(small)

        if not encodings:
            print(f"⚠️ [THREAD] Không nhận diện được khuôn mặt cho {ma_nv}.")
            return

        face_encoding = encodings[0]
        cursor.execute("""
            IF EXISTS(SELECT 1 FROM KhuonMat WHERE MaNV=? AND TrangThai=1)
                UPDATE KhuonMat SET MaHoaNhanDang=? WHERE MaNV=? AND TrangThai=1
            ELSE
                INSERT INTO KhuonMat (MaNV, MaHoaNhanDang, TrangThai)
                VALUES (?, ?, 1)
        """, (ma_nv, face_encoding.tobytes(), ma_nv, ma_nv, face_encoding.tobytes()))
        conn.commit()
        print(f"✅ [THREAD] Đã encode xong cho {ma_nv} ({tm.time() - start_encode:.2f}s)")
    except Exception as e:
        print(f"❌ [THREAD] Lỗi encode nền: {e}")
    finally:
        conn.close()


# ============================================================
# 👥 TRANG DANH SÁCH NHÂN VIÊN
# ============================================================
@employee_bp.route("/employees")
@require_role("admin", "hr", "quanlyphongban")
def employee_list():
    conn = get_sql_connection()
    cursor = conn.cursor()

    role = session.get("role")
    username = session.get("username")

    # ============================================================
    # 1️⃣ Nếu là Quản lý phòng ban → chỉ xem nhân viên phòng mình
    # ============================================================
    ma_pb_user = None
    if role == "quanlyphongban":
        cursor.execute("""
            SELECT nv.MaPB
            FROM NhanVien nv
            JOIN TaiKhoan tk ON nv.MaNV = tk.MaNV
            WHERE tk.TenDangNhap = ?
        """, (username,))
        row = cursor.fetchone()
        if row:
            ma_pb_user = row[0]

    # ============================================================
    # 2️⃣ Tìm kiếm và sắp xếp
    # ============================================================
    keyword = request.args.get("q", "").strip()
    sort = request.args.get("sort", "ma")
    order = request.args.get("order", "asc")

    # ============================================================
    # 3️⃣ Truy vấn danh sách nhân viên
    # ============================================================
    query = """
        SELECT nv.MaNV, nv.HoTen, nv.Email, nv.ChucVu, nv.NgaySinh,
               pb.TenPB, km.DuongDanAnh
        FROM NhanVien nv
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat km ON nv.MaNV = km.MaNV
        WHERE nv.TrangThai = 1
    """
    params = []

    if ma_pb_user:
        query += " AND nv.MaPB = ?"
        params.append(ma_pb_user)

    if keyword:
        query += """
            AND (nv.HoTen LIKE ? OR nv.MaNV LIKE ? OR nv.ChucVu LIKE ? OR pb.TenPB LIKE ?)
        """
        params.extend([f"%{keyword}%"] * 4)

    sort_map = {
        "ma": "nv.MaNV",
        "ten": "nv.HoTen",
        "phongban": "pb.TenPB",
        "chucvu": "nv.ChucVu"
    }
    sort_col = sort_map.get(sort, "nv.MaNV")
    order_sql = "ASC" if order == "asc" else "DESC"
    query += f" ORDER BY {sort_col} {order_sql}"

    cursor.execute(query, params)
    rows = cursor.fetchall()
    columns = [col[0] for col in cursor.description]

    employees = []
    for row in rows:
        emp = dict(zip(columns, row))
        avatar = emp.get("DuongDanAnh")

        if avatar:
            duong_dan = avatar.replace("\\", "/")
            if not duong_dan.startswith("/"):
                duong_dan = "/" + duong_dan
            emp["AnhDaiDien"] = duong_dan
        else:
            emp["AnhDaiDien"] = "/photos/default.jpg"

        employees.append(emp)

    # ============================================================
    # 5️⃣ Thống kê
    # ============================================================
    total_employees = total_departments = total_managers = birthday_this_month = 0
    total_employees_in_department = total_shifts_in_department = 0
    attendance_rate = 0
    total_managers_in_department = 0

    if role in ("admin", "hr"):
        cursor.execute("SELECT COUNT(*) FROM NhanVien WHERE TrangThai = 1")
        total_employees = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM PhongBan WHERE TrangThai = 1")
        total_departments = cursor.fetchone()[0] or 0

        cursor.execute("""
            SELECT COUNT(*)
            FROM NhanVien
            WHERE ChucVu LIKE N'%Trưởng phòng%' AND TrangThai = 1
        """)
        total_managers = cursor.fetchone()[0] or 0

        cursor.execute("""
            SELECT COUNT(*)
            FROM NhanVien
            WHERE TrangThai = 1
              AND TRY_CONVERT(DATE, NgaySinh, 103) IS NOT NULL
              AND MONTH(TRY_CONVERT(DATE, NgaySinh, 103)) = MONTH(GETDATE())
        """)
        birthday_this_month = cursor.fetchone()[0] or 0

    elif role == "quanlyphongban" and ma_pb_user:
        cursor.execute("""
            SELECT COUNT(*) FROM NhanVien WHERE MaPB = ? AND TrangThai = 1
        """, (ma_pb_user,))
        total_employees_in_department = cursor.fetchone()[0] or 0

        cursor.execute("""
            SELECT COUNT(*) FROM NhanVien
            WHERE MaPB = ? AND TrangThai = 1 AND ChucVu LIKE N'%Trưởng phòng%'
        """, (ma_pb_user,))
        total_managers_in_department = cursor.fetchone()[0] or 0

        cursor.execute("""
            SELECT COUNT(DISTINCT llv.MaCa)
            FROM LichLamViec llv
            JOIN NhanVien nv ON llv.MaNV = nv.MaNV
            WHERE nv.MaPB = ? AND llv.DaXoa = 1
        """, (ma_pb_user,))
        total_shifts_in_department = cursor.fetchone()[0] or 0

        cursor.execute("""
            SELECT COUNT(*) AS Tong, SUM(CASE WHEN cc.TrangThai = 1 THEN 1 ELSE 0 END) AS DiLam
            FROM ChamCong cc
            JOIN NhanVien nv ON cc.MaNV = nv.MaNV
            WHERE nv.MaPB = ? AND cc.DaXoa = 1
        """, (ma_pb_user,))
        row = cursor.fetchone()
        total_cc = row[0] or 1
        total_present = row[1] or 0
        attendance_rate = round(total_present / total_cc * 100, 2)

        cursor.execute("""
            SELECT COUNT(*) FROM NhanVien
            WHERE MaPB = ? AND TrangThai = 1
              AND TRY_CONVERT(DATE, NgaySinh, 103) IS NOT NULL
              AND MONTH(TRY_CONVERT(DATE, NgaySinh, 103)) = MONTH(GETDATE())
        """, (ma_pb_user,))
        birthday_this_month = cursor.fetchone()[0] or 0

    conn.close()

    if role == "hr":
        template = "hr_employees.html"
    elif role == "quanlyphongban":
        template = "qlpb_employees.html"
    else:
        template = "employees.html"

    return render_template(
        template,
        employees=employees,
        total_employees=total_employees,
        total_departments=total_departments,
        total_managers=total_managers,
        birthday_this_month=birthday_this_month,
        total_employees_in_department=total_employees_in_department,
        total_managers_in_department=total_managers_in_department,
        total_shifts_in_department=total_shifts_in_department,
        attendance_rate=attendance_rate,
        keyword=keyword,
        sort=sort,
        order=order,
        role=role,
        ma_pb_user=ma_pb_user
    )

# ============================================================
# 👤 TRANG CHI TIẾT NHÂN VIÊN
# ============================================================
@employee_bp.route("/employees/<ma_nv>")
@require_role("admin", "hr", "quanlyphongban")
def employee_detail(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()
    role = session.get("role")
    username = session.get("username")

    # --- Nếu là quản lý phòng ban → chỉ xem nhân viên cùng phòng ---
    if role == "quanlyphongban":
        cursor.execute("""
            SELECT nv.MaPB
            FROM NhanVien nv
            JOIN TaiKhoan tk ON nv.MaNV = tk.MaNV
            WHERE tk.TenDangNhap = ?
        """, (username,))
        row = cursor.fetchone()
        ma_pb_user = row[0] if row else None

        cursor.execute("SELECT MaPB FROM NhanVien WHERE MaNV = ?", (ma_nv,))
        emp_pb = cursor.fetchone()
        if not emp_pb or emp_pb[0] != ma_pb_user:
            conn.close()
            flash("❌ Bạn chỉ được xem nhân viên thuộc phòng ban của mình!", "error")
            return redirect(url_for("employee_bp.employee_list"))

    # --- Lấy thông tin nhân viên ---
    cursor.execute("""
        SELECT 
            nv.MaNV, nv.MaHienThi, nv.HoTen, nv.Email, nv.SDT, nv.GioiTinh, nv.NgaySinh,
            nv.DiaChi, pb.TenPB AS TenPhongBan, nv.ChucVu, nv.TrangThai,
            nv.NgayVaoLam, nv.NgayTao, nv.NgayCapNhat, km.DuongDanAnh
        FROM NhanVien nv
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat km ON nv.MaNV = km.MaNV
        WHERE nv.MaNV = ?
    """, (ma_nv,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash("Không tìm thấy nhân viên!", "error")
        return redirect(url_for("employee_bp.employee_list"))

    columns = [col[0] for col in cursor.description]
    employee = dict(zip(columns, row))

    # --- Định dạng ngày tháng ---
    def fmt(date_value):
        if not date_value:
            return "—"
        try:
            if isinstance(date_value, str):
                return date_value[:10]
            return date_value.strftime("%d/%m/%Y")
        except Exception:
            return str(date_value)

    employee["NgaySinh"] = fmt(employee.get("NgaySinh"))
    employee["NgayVaoLam"] = fmt(employee.get("NgayVaoLam"))
    employee["NgayTao"] = fmt(employee.get("NgayTao"))
    employee["NgayCapNhat"] = fmt(employee.get("NgayCapNhat"))

    # 🔹 Giới tính
    employee["GioiTinhText"] = "Nam" if employee.get("GioiTinh") == 1 else "Nữ"

    # 🔹 Ảnh đại diện
    avatar = employee.get("DuongDanAnh")
    if avatar:
        duong_dan = avatar.replace("\\", "/")
        if not duong_dan.startswith("/"):
            duong_dan = "/" + duong_dan
        employee["AnhDaiDien"] = duong_dan
    else:
        employee["AnhDaiDien"] = "/photos/default.jpg"

    # 🔹 Trạng thái
    employee["TrangThaiText"] = "Đang làm việc" if employee.get("TrangThai") == 1 else "Ngừng làm việc"

    # --- Ghi log xem chi tiết ---
    try:
        cursor.execute("""
            INSERT INTO LichSuThayDoi 
                (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, (
            "NhanVien",
            ma_nv,
            "Xem chi tiết",
            "Toàn bộ dòng",
            None,
            employee.get("HoTen"),
            username or "unknown"
        ))
        conn.commit()
    except Exception as e:
        print("⚠️ Lỗi ghi log xem chi tiết:", e)

    conn.close()

    # ============================================================
    # 🔹 Render đúng template theo vai trò
    # ============================================================
    if role == "hr":
        template_name = "hr_employee_detail.html"
    elif role == "quanlyphongban":
        template_name = "qlpb_employee_detail.html"
    else:
        template_name = "employee_detail.html"

    return render_template(template_name, employee=employee, role=role)

# ============================================================
# ➕ THÊM NHÂN VIÊN MỚI
# ============================================================
@employee_bp.route("/employees/add", methods=["GET", "POST"])
@require_role("admin")
def add_employee_web():
    from core.db_utils import get_phongbans  # Nếu có tách ra core riêng
    import os, base64, threading
    from core.db_utils import get_sql_connection
    from core.face_utils import encode_and_save
    from routes.capture_photo_and_save import capture_photo_and_save

    departments = get_phongbans()

    if request.method == "POST":
        HoTen = request.form.get("HoTen", "").strip()
        Email = request.form.get("Email", "").strip()
        SDT = request.form.get("SDT", "").strip()
        GioiTinh = int(request.form.get("GioiTinh", 1))
        NgaySinh = request.form.get("NgaySinh")
        MaPB = request.form.get("MaPB")
        DiaChi = request.form.get("DiaChi", "").strip()
        ChucVu = request.form.get("ChucVu", "").strip()

        conn = None
        try:
            conn = get_sql_connection()
            cursor = conn.cursor()

            # 1️⃣ Sinh mã nhân viên mới
            cursor.execute("SELECT TOP 1 MaNV FROM NhanVien ORDER BY MaNV DESC")
            row = cursor.fetchone()
            next_num = int(''.join(filter(str.isdigit, row[0]))) + 1 if row and row[0] else 1
            MaNV = f"NV{next_num:05d}"

            # 2️⃣ Kiểm tra trùng email/SĐT
            cursor.execute("SELECT COUNT(*) FROM NhanVien WHERE Email = ? OR SDT = ?", (Email, SDT))
            if cursor.fetchone()[0] > 0:
                flash("⚠️ Email hoặc SĐT đã tồn tại!", "warning")
                conn.close()
                return redirect(url_for("employee_bp.employee_list"))

            # 3️⃣ Thêm nhân viên
            cursor.execute("""
                INSERT INTO NhanVien 
                (MaNV, HoTen, Email, SDT, GioiTinh, NgaySinh, MaPB, DiaChi, ChucVu, TrangThai, NgayTao)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, GETDATE())
            """, (MaNV, HoTen, Email, SDT, GioiTinh, NgaySinh, MaPB, DiaChi, ChucVu))

            # 3️⃣.1️⃣ Tự động tạo tài khoản đăng nhập
            from werkzeug.security import generate_password_hash
            role = "nhanvien"
            role_id = 4

            if "hr" in ChucVu.lower():
                role = "hr"
                role_id = 2
            elif "quản lý" in ChucVu.lower() or "trưởng phòng" in ChucVu.lower():
                role = "quanlyphongban"
                role_id = 3

            username = MaNV
            password_hash = generate_password_hash("123456", method="scrypt")

            cursor.execute("""
                INSERT INTO TaiKhoan 
                (TenDangNhap, MatKhauHash, VaiTro, MaVT, TrangThai, NgayTao, MaNV, DaDangKyKhuonMat)
                VALUES (?, ?, ?, ?, 1, GETDATE(), ?, 0)
            """, (username, password_hash, role, role_id, MaNV))

            print(f"🔑 Đã tạo tài khoản cho {MaNV} ({role.upper()}) — mật khẩu: 123456")

            # 4️⃣ Lưu nhật ký thêm mới
            cursor.execute("""
                INSERT INTO LichSuThayDoi
                (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien)
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, (
                "NhanVien",
                MaNV,
                "THÊM",
                "Toàn bộ dòng",
                None,
                f"Họ tên={HoTen}, Email={Email}, Chức vụ={ChucVu}, Phòng ban={MaPB}",
                session.get("username", "admin")
            ))

            conn.commit()
            print(f"✅ Đã thêm nhân viên {MaNV} ({HoTen}) thành công.")

            # 5️⃣ Xử lý ảnh khuôn mặt
            image_data = request.form.get("face_image")
            image_path = None

            if image_data:
                print("🖼️ Nhận ảnh base64 từ trình duyệt, đang lưu...")
                image_data = image_data.split(",")[1]
                image_bytes = base64.b64decode(image_data)

                os.makedirs("photos", exist_ok=True)
                image_path = os.path.join("photos", f"{MaNV}.jpg")
                with open(image_path, "wb") as f:
                    f.write(image_bytes)

                encode_and_save(MaNV, image_path, conn)
                flash("✅ Đã thêm nhân viên và lưu ảnh khuôn mặt từ trình duyệt!", "success")

            else:
                print("📸 Không có ảnh từ trình duyệt → chụp bằng camera server...")

                def capture_and_encode():
                    img_path = capture_photo_and_save(MaNV)
                    if img_path and os.path.exists(img_path):
                        conn_inner = get_sql_connection()
                        try:
                            encode_and_save(MaNV, img_path, conn_inner)
                            print(f"✅ Đã encode khuôn mặt cho {MaNV}")
                        except Exception as e:
                            print(f"⚠️ Lỗi encode: {e}")
                        finally:
                            conn_inner.close()
                    else:
                        conn_del = get_sql_connection()
                        cur = conn_del.cursor()
                        cur.execute("DELETE FROM NhanVien WHERE MaNV = ?", (MaNV,))
                        conn_del.commit()
                        conn_del.close()
                        print(f"🗑️ Đã xóa nhân viên {MaNV} do không có ảnh hợp lệ.")

                threading.Thread(target=capture_and_encode, daemon=True).start()
                flash("✅ Nhân viên đã thêm, hệ thống đang chụp và xử lý khuôn mặt...", "info")

            conn.close()
            return redirect(url_for("employee_bp.employee_list"))

        except Exception as e:
            print(f"❌ Lỗi khi thêm nhân viên: {e}")
            flash(f"❌ Lỗi khi thêm nhân viên: {e}", "danger")
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except:
                    pass
            return redirect(url_for("employee_bp.employee_list"))

    # Nếu GET → hiển thị form thêm nhân viên
    return render_template("add_employee.html", departments=departments)


# ============================================================
# ❌ XÓA MỀM 1 NHÂN VIÊN
# ============================================================
@employee_bp.route("/employees/delete/<ma_nv>")
@require_role("admin", "hr")
def delete_employee_web(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # 🔹 Lấy tên nhân viên
        cursor.execute("SELECT HoTen FROM NhanVien WHERE MaNV = ?", (ma_nv,))
        row = cursor.fetchone()
        old_name = row[0] if row else "(Không tìm thấy)"

        # 🔹 Không cho phép xóa quản lý phòng ban
        cursor.execute("SELECT MaPB FROM PhongBan WHERE QuanLyPB = ?", (ma_nv,))
        if cursor.fetchone():
            flash(f"⚠️ Nhân viên {old_name} ({ma_nv}) đang là quản lý phòng ban, không thể xóa!", "warning")
            conn.close()
            return redirect(url_for("employee_bp.employee_list"))

        # 🔹 Xóa mềm nhân viên
        cursor.execute("""
            UPDATE NhanVien
            SET TrangThai = 0, NgayCapNhat = GETDATE()
            WHERE MaNV = ?
        """, (ma_nv,))

        # 🔹 Vô hiệu hóa tài khoản
        cursor.execute("UPDATE TaiKhoan SET TrangThai = 0 WHERE MaNV = ?", (ma_nv,))

        # 🔹 Ghi log
        nguoi_thuc_hien = session.get("username", "Hệ thống")
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("NhanVien", ma_nv, "Xóa mềm", "TrangThai", 1, 0, nguoi_thuc_hien))

        conn.commit()
        flash(f"✅ Đã ẩn (xóa mềm) nhân viên {old_name} ({ma_nv}).", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa mềm nhân viên: {e}", "danger")

    finally:
        conn.close()

    return redirect(url_for("employee_bp.employee_list"))


# ============================================================
# ❌ XÓA MỀM NHIỀU NHÂN VIÊN
# ============================================================
@employee_bp.route("/employees/delete_selected", methods=["POST"])
@require_role("admin", "hr")
def delete_selected_employees():
    selected_ids = request.form.getlist("selected_employees")
    if not selected_ids:
        flash("⚠️ Chưa chọn nhân viên nào để xóa!", "warning")
        return redirect(url_for("employee_bp.employee_list"))

    conn = get_sql_connection()
    cursor = conn.cursor()

    skipped = []  # nhân viên không thể xóa (đang là quản lý)
    deleted = []  # nhân viên đã xóa

    try:
        nguoi_thuc_hien = session.get("username", "Hệ thống")

        for ma_nv in selected_ids:
            # 🔹 Kiểm tra nếu là quản lý phòng ban → bỏ qua
            cursor.execute("SELECT MaPB FROM PhongBan WHERE QuanLyPB = ?", (ma_nv,))
            if cursor.fetchone():
                skipped.append(ma_nv)
                continue

            # 🔹 Lấy họ tên nhân viên (để ghi log)
            cursor.execute("SELECT HoTen FROM NhanVien WHERE MaNV = ?", (ma_nv,))
            row = cursor.fetchone()
            old_name = row[0] if row else "(Không tìm thấy)"

            # 🔹 Xóa mềm nhân viên
            cursor.execute("""
                UPDATE NhanVien
                SET TrangThai = 0, NgayCapNhat = GETDATE()
                WHERE MaNV = ?
            """, (ma_nv,))

            # 🔹 Vô hiệu hóa tài khoản
            cursor.execute("UPDATE TaiKhoan SET TrangThai = 0 WHERE MaNV = ?", (ma_nv,))

            # 🔹 Ghi log
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, ("NhanVien", ma_nv, "Xóa mềm", "TrangThai", 1, 0, nguoi_thuc_hien))

            deleted.append(f"{old_name} ({ma_nv})")

        conn.commit()

        # 🔹 Hiển thị kết quả
        msg = ""
        if deleted:
            msg += f"🗑 Đã xóa mềm {len(deleted)} nhân viên. "
        if skipped:
            msg += f"⚠️ {len(skipped)} nhân viên đang là quản lý, không thể xóa."
        flash(msg.strip(), "info" if skipped else "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa nhiều nhân viên: {e}", "danger")

    finally:
        conn.close()

    return redirect(url_for("employee_bp.employee_list"))


# ============================================================
# 🗃 DANH SÁCH NHÂN VIÊN ĐÃ XÓA
# ============================================================
@employee_bp.route("/employees/deleted")
@require_role("admin")
def employee_list_deleted():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # 🧩 Lấy danh sách nhân viên đã xóa (TrangThai = 0)
        cursor.execute("""
            SELECT 
                nv.MaNV, 
                nv.HoTen, 
                nv.Email, 
                nv.SDT, 
                nv.ChucVu, 
                pb.TenPB, 
                ql.HoTen AS TenQuanLy,
                nv.NgayCapNhat,
                k.DuongDanAnh
            FROM NhanVien nv
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            LEFT JOIN NhanVien ql ON pb.QuanLyPB = ql.MaNV
            LEFT JOIN KhuonMat k ON nv.MaNV = k.MaNV
            WHERE nv.TrangThai = 0
            ORDER BY nv.NgayCapNhat DESC
        """)
        deleted_employees = cursor.fetchall()

        # 🏢 Lấy danh sách phòng ban đã xóa (TrangThai = 0)
        cursor.execute("""
            SELECT 
                pb.MaPB, 
                pb.TenPB, 
                ql.HoTen AS TenQuanLy, 
                pb.NgayTao
            FROM PhongBan pb
            LEFT JOIN NhanVien ql ON pb.QuanLyPB = ql.MaNV
            WHERE pb.TrangThai = 0
            ORDER BY pb.NgayTao DESC
        """)
        deleted_departments = cursor.fetchall()

    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách đã xóa: {str(e)}", "danger")
        deleted_employees, deleted_departments = [], []

    finally:
        conn.close()

    return render_template(
        "deleted_records.html",
        deleted_employees=deleted_employees,
        deleted_departments=deleted_departments,
        active_tab="employees"
    )

# ============================================================
# ♻️ KHÔI PHỤC NHÂN VIÊN
# ============================================================
@employee_bp.route("/employees/restore/<ma_nv>")
@require_role("admin")
def restore_employee(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # 🔹 Khôi phục trạng thái nhân viên
        cursor.execute("""
            UPDATE NhanVien
            SET TrangThai = 1, NgayCapNhat = GETDATE()
            WHERE MaNV = ?
        """, (ma_nv,))
        cursor.execute("UPDATE TaiKhoan SET TrangThai = 1 WHERE MaNV = ?", (ma_nv,))

        # 🔹 Ghi lịch sử
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("NhanVien", ma_nv, "Khôi phục", "TrangThai", 0, 1, session.get("username", "Hệ thống")))

        conn.commit()
        flash(f"♻️ Đã khôi phục nhân viên {ma_nv} thành công.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục nhân viên: {e}", "danger")

    finally:
        conn.close()

    # 🔹 Trả về danh sách nhân viên đã xóa
    return redirect(url_for("employee_bp.employee_list_deleted"))


# ============================================================
# ♻️ KHÔI PHỤC NHIỀU NHÂN VIÊN
# ============================================================
@employee_bp.route("/employees/restore_selected", methods=["POST"])
@require_role("admin")
def restore_selected_employees():
    selected_ids = request.form.getlist("selected_employees")
    if not selected_ids:
        flash("⚠️ Chưa chọn nhân viên nào để khôi phục!", "warning")
        return redirect(url_for("employee_bp.employee_list_deleted"))

    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        for ma_nv in selected_ids:
            # 🔹 Cập nhật trạng thái
            cursor.execute("""
                UPDATE NhanVien
                SET TrangThai = 1, NgayCapNhat = GETDATE()
                WHERE MaNV = ?
            """, (ma_nv,))
            cursor.execute("UPDATE TaiKhoan SET TrangThai = 1 WHERE MaNV = ?", (ma_nv,))

            # 🔹 Ghi lịch sử khôi phục
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, ("NhanVien", ma_nv, "Khôi phục", "TrangThai", 0, 1, session.get("username", "Hệ thống")))

        conn.commit()
        flash(f"♻️ Đã khôi phục {len(selected_ids)} nhân viên thành công.", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục nhiều nhân viên: {e}", "danger")

    finally:
        conn.close()

    return redirect(url_for("employee_bp.employee_list_deleted"))

# ============================================================
# ✏️ CHỈNH SỬA NHÂN VIÊN
# ============================================================
@employee_bp.route("/employees/edit/<ma_nv>", methods=["GET", "POST"], endpoint="edit_employee_web")
@require_role("admin", "hr", "quanlyphongban")
def edit_employee_web(ma_nv):
    import os
    conn = get_sql_connection()
    cursor = conn.cursor()

    role = session.get("role")
    username = session.get("username")

    # 🔹 Nếu là quản lý phòng ban → kiểm tra nhân viên có thuộc phòng ban mình không
    if role == "quanlyphongban":
        cursor.execute("""
            SELECT nv.MaPB
            FROM NhanVien nv
            JOIN TaiKhoan tk ON nv.MaNV = tk.MaNV
            WHERE tk.TenDangNhap = ?
        """, (username,))
        row = cursor.fetchone()
        ma_pb_user = row[0] if row else None

        cursor.execute("SELECT MaPB FROM NhanVien WHERE MaNV = ?", (ma_nv,))
        emp_pb = cursor.fetchone()
        if not emp_pb or emp_pb[0] != ma_pb_user:
            conn.close()
            flash("❌ Bạn chỉ được chỉnh sửa nhân viên thuộc phòng ban của mình!", "error")
            return redirect(url_for("employee_bp.employee_list"))

    # --- Lấy thông tin nhân viên ---
    cursor.execute("""
        SELECT nv.MaNV, nv.MaHienThi, nv.HoTen, nv.Email, nv.SDT, nv.GioiTinh, nv.NgaySinh, nv.DiaChi,
               nv.MaPB, nv.ChucVu, nv.TrangThai, pb.TenPB, km.DuongDanAnh
        FROM NhanVien nv
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat km ON nv.MaNV = km.MaNV
        WHERE nv.MaNV = ?
    """, (ma_nv,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        flash(f"❌ Không tìm thấy nhân viên {ma_nv}", "error")
        return redirect(url_for("employee_bp.employee_list"))

    columns = [col[0] for col in cursor.description]
    employee = dict(zip(columns, row))

    # --- Ảnh đại diện ---
    avatar = employee.get("DuongDanAnh")
    if avatar and avatar.strip():
        avatar = avatar.replace("\\", "/")
        if not avatar.startswith("/"):
            avatar = f"/{avatar}"
        employee["AnhDaiDien"] = avatar
    else:
        employee["AnhDaiDien"] = "/photos/default.jpg"

    # --- Danh sách phòng ban ---
    cursor.execute("SELECT MaPB, TenPB FROM PhongBan")
    departments = [dict(zip([c[0] for c in cursor.description], r)) for r in cursor.fetchall()]
    conn.close()

    # --- Nếu người dùng cập nhật ---
    if request.method == "POST":
        hoten = request.form.get("HoTen", "").strip()
        email = request.form.get("Email", "").strip()
        sdt = request.form.get("SDT", "").strip()
        ngaysinh = request.form.get("NgaySinh", "").strip() or None
        diachi = request.form.get("DiaChi", "").strip()
        ma_pb_moi = request.form.get("MaPB", "").strip()
        chucvu = request.form.get("ChucVu", "").strip()

        gioitinh = 1 if request.form.get("GioiTinh", "").lower() in ["1", "nam", "true"] else 0
        trangthai = 1 if request.form.get("TrangThai", "").lower() in ["1", "hoạt động", "active", "true"] else 0

        file = request.files.get("avatar")
        nguoi_thuc_hien = session.get("username", "Hệ thống")

        conn = get_sql_connection()
        cursor = conn.cursor()

        # 🔹 Lấy phòng ban và mã hiển thị hiện tại
        cursor.execute("SELECT MaPB, MaHienThi FROM NhanVien WHERE MaNV=?", (ma_nv,))
        row = cursor.fetchone()
        old_pb = row[0] if row else None
        old_ma_hienthi = row[1] if row else None

        # 🟦 Nếu đổi phòng ban → sinh MaHienThi mới
        if ma_pb_moi != old_pb:
            cursor.execute("SELECT MaHienThi FROM PhongBan WHERE MaPB=?", (ma_pb_moi,))
            row = cursor.fetchone()
            pb_short = row[0].strip().upper() if row and row[0] else ma_pb_moi[-2:].upper()
            if len(pb_short) < 1:
                pb_short = "XX"

            cursor.execute("""
                SELECT TOP 1 MaHienThi FROM NhanVien 
                WHERE MaPB=? AND MaHienThi LIKE ?
                ORDER BY MaHienThi DESC
            """, (ma_pb_moi, f"NV{pb_short}%"))
            row = cursor.fetchone()
            if row and row[0]:
                num_part = ''.join([c for c in row[0] if c.isdigit()])
                next_num = int(num_part) + 1 if num_part else 1
            else:
                next_num = 1
            new_ma_hienthi = f"NV{pb_short}{next_num}"

            # 🔹 Cập nhật nhân viên
            cursor.execute("""
                UPDATE NhanVien
                SET HoTen=?, Email=?, SDT=?, GioiTinh=?, NgaySinh=?, DiaChi=?, 
                    MaPB=?, ChucVu=?, TrangThai=?, NgayCapNhat=GETDATE()
                WHERE MaNV=?
            """, (hoten, email, sdt, gioitinh, ngaysinh, diachi,
                  ma_pb_moi, chucvu, trangthai, ma_nv))

            # 🔹 Ghi log
            cursor.execute("""
                INSERT INTO LichSuThayDoi 
                (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, NguoiThucHien)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ("NhanVien", ma_nv, "Sửa", "MaPB", old_pb, ma_pb_moi, nguoi_thuc_hien))
            cursor.execute("""
                INSERT INTO LichSuThayDoi 
                (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi, NguoiThucHien)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, ("NhanVien", ma_nv, "Sửa", "MaHienThi", old_ma_hienthi, new_ma_hienthi, nguoi_thuc_hien))
        else:
            # 🔹 Không đổi phòng ban
            cursor.execute("""
                UPDATE NhanVien
                SET HoTen=?, Email=?, SDT=?, GioiTinh=?, NgaySinh=?, DiaChi=?, 
                    MaPB=?, ChucVu=?, TrangThai=?
                WHERE MaNV=?
            """, (hoten, email, sdt, gioitinh, ngaysinh, diachi,
                  ma_pb_moi, chucvu, trangthai, ma_nv))
            new_ma_hienthi = old_ma_hienthi

        # --- Ảnh đại diện ---
        if file and file.filename != "":
            os.makedirs("photos", exist_ok=True)
            filename = f"{new_ma_hienthi}.jpg"
            save_path = os.path.join("photos", filename)
            file.save(save_path)
            db_path = f"photos/{filename}"

            cursor.execute("SELECT COUNT(*) FROM KhuonMat WHERE MaNV=?", (ma_nv,))
            exists = cursor.fetchone()[0]
            if exists:
                cursor.execute("UPDATE KhuonMat SET DuongDanAnh=? WHERE MaNV=?", (db_path, ma_nv))
            else:
                cursor.execute("""
                    INSERT INTO KhuonMat (MaNV, DuongDanAnh, TrangThai) 
                    VALUES (?, ?, 1)
                """, (ma_nv, db_path))

            # 🔹 Ghi log ảnh
            cursor.execute("""
                INSERT INTO LichSuThayDoi
                (TenBang, MaBanGhi, HanhDong, TruongThayDoi, GiaTriMoi, NguoiThucHien)
                VALUES (?, ?, ?, ?, ?, ?)
            """, ("KhuonMat", ma_nv, "Cập nhật", "DuongDanAnh", db_path, nguoi_thuc_hien))

        conn.commit()
        conn.close()

        flash("✅ Cập nhật thông tin nhân viên thành công!", "success")
        return redirect(url_for("employee_bp.employee_detail", ma_nv=ma_nv))

    return render_template("edit_employee.html", employee=employee, departments=departments)

# ============================================================
# 🧾 LỊCH LÀM VIỆC CỦA NHÂN VIÊN
# ============================================================
@employee_bp.route("/my_schedule")
@require_role("nhanvien")
def my_schedule():
    username = session.get("username")
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT nv.MaNV, nv.HoTen, pb.TenPB, clv.TenCa, llv.NgayLam, 
                   clv.GioBatDau, clv.GioKetThuc
            FROM LichLamViec llv
            JOIN NhanVien nv ON llv.MaNV = nv.MaNV
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            LEFT JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
            JOIN TaiKhoan tk ON tk.MaNV = nv.MaNV
            WHERE tk.TenDangNhap = ? AND llv.DaXoa = 1
            ORDER BY llv.NgayLam DESC
        """, (username,))
        rows = cursor.fetchall()

    except Exception as e:
        flash(f"❌ Lỗi khi tải lịch làm việc: {e}", "danger")
        rows = []
    finally:
        conn.close()

    # ✅ Định dạng thời gian
    def fmt_time(t):
        if not t:
            return ""
        if hasattr(t, "strftime"):
            return t.strftime("%H:%M")
        return str(t)[:5]

    schedules = []
    for r in rows:
        ma_nv, hoten, tenpb, tenca, ngaylam, giobd, giokt = r
        schedules.append({
            "MaNV": ma_nv,
            "HoTen": hoten,
            "TenPB": tenpb,
            "TenCa": tenca,
            "NgayLam": ngaylam,
            "GioBatDau": fmt_time(giobd),
            "GioKetThuc": fmt_time(giokt)
        })

    return render_template("my_schedule.html", schedules=schedules)

# ============================================================
# 🏠 TRANG CHÍNH CỦA NHÂN VIÊN
# ============================================================
@employee_bp.route("/employee/dashboard")
@require_role("nhanvien")
def employee_dashboard():
    if "manv" not in session:
        return redirect(url_for("login"))

    ma_nv = session["manv"]
    ho_ten_session = session.get("hoten", "")

    conn = get_sql_connection()
    cursor = conn.cursor()

    # 1️⃣ Thông tin nhân viên
    cursor.execute("""
        SELECT nv.MaNV, nv.HoTen, nv.Email, nv.NgaySinh, nv.ChucVu, nv.DiaChi, 
               pb.TenPB AS PhongBan, nv.LuongGioCoBan, k.DuongDanAnh
        FROM NhanVien nv
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat k ON nv.MaNV = k.MaNV
        WHERE nv.MaNV = ?
    """, (ma_nv,))
    row = cursor.fetchone()
    nhanvien = dict(zip([col[0] for col in cursor.description], row)) if row else {}

    # 2️⃣ Ca làm việc hôm nay
    cursor.execute("""
        SELECT clv.TenCa, clv.GioBatDau, clv.GioKetThuc
        FROM LichLamViec llv
        JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
        WHERE llv.MaNV = ?
          AND CAST(llv.NgayLam AS DATE) = CAST(GETDATE() AS DATE)
          AND llv.DaXoa = 1
    """, (ma_nv,))
    ca_rows = cursor.fetchall()

    def fmt_time(t):
        if not t:
            return ""
        if hasattr(t, "strftime"):
            return t.strftime("%H:%M")
        return str(t)[:5]

    ca_hom_nay = ", ".join(
        [f"{r[0]} ({fmt_time(r[1])} - {fmt_time(r[2])})" for r in ca_rows]
    ) if ca_rows else "Không có ca hôm nay"

    # 3️⃣ Lịch sử chấm công
    cursor.execute("""
        SELECT MaChamCong, NgayChamCong, GioVao, GioRa, TrangThai
        FROM ChamCong
        WHERE MaNV = ?
        ORDER BY NgayChamCong DESC
    """, (ma_nv,))
    chamcong = [dict(zip([col[0] for col in cursor.description], r)) for r in cursor.fetchall()]

    # 4️⃣ Lịch sử hoạt động
    cursor.execute("""
        SELECT ThoiGian, TenBang, HanhDong, TruongThayDoi, GiaTriCu, GiaTriMoi
        FROM LichSuThayDoi
        WHERE NguoiThucHien = ?
        ORDER BY ThoiGian DESC
    """, (ho_ten_session,))
    lichsu = [dict(zip([col[0] for col in cursor.description], r)) for r in cursor.fetchall()]

    conn.close()

    return render_template(
        "employee_dashboard.html",
        nhanvien=nhanvien,
        chamcong=chamcong,
        lichsu=lichsu,
        ho_ten=nhanvien.get("HoTen", "(Không rõ)"),
        phongban=nhanvien.get("PhongBan", "(Chưa có)"),
        ca_hom_nay=ca_hom_nay,
        anh_nv=nhanvien.get("DuongDanAnh", "")
    )


# ============================================================
# 🧍‍♂️ TRANG THÔNG TIN NHÂN VIÊN
# ============================================================
@employee_bp.route("/employee/profile")
@require_role("nhanvien")
def employee_profile():
    ma_nv = session.get("manv")

    if not ma_nv:
        flash("⚠️ Phiên làm việc đã hết hạn. Vui lòng đăng nhập lại.", "warning")
        return redirect(url_for("login"))

    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            nv.MaNV, nv.HoTen, nv.Email, nv.SDT, nv.GioiTinh, nv.NgaySinh, nv.DiaChi, 
            nv.ChucVu, pb.TenPB, km.DuongDanAnh
        FROM NhanVien nv
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat km ON nv.MaNV = km.MaNV
        WHERE nv.MaNV = ?
    """, (ma_nv,))
    emp = cursor.fetchone()

    if not emp:
        conn.close()
        flash("Không tìm thấy thông tin nhân viên!", "danger")
        return redirect(url_for("login"))

    fields = [col[0] for col in cursor.description]
    employee = dict(zip(fields, emp))
    conn.close()

    # Ảnh đại diện
    avatar = employee.get("DuongDanAnh")
    if avatar and avatar.strip():
        avatar = avatar.replace("\\", "/")
        if not avatar.startswith("/"):
            avatar = f"/{avatar}"
        employee["AnhDaiDien"] = avatar
    else:
        employee["AnhDaiDien"] = "/photos/default.jpg"

    # Giới tính
    gt = employee.get("GioiTinh")
    if gt is None:
        employee["GioiTinhText"] = "Chưa cập nhật"
    elif gt == 1:
        employee["GioiTinhText"] = "Nam"
    else:
        employee["GioiTinhText"] = "Nữ"

    return render_template("employee_profile.html", employee=employee)


# ============================================================
# ✏️ CHỈNH SỬA HỒ SƠ CÁ NHÂN
# ============================================================
@employee_bp.route("/profile/edit", methods=["GET", "POST"])
@require_role("nhanvien")
def edit_profile():
    username = session.get("username")

    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Lấy thông tin nhân viên ---
    cursor.execute("""
        SELECT 
            nv.MaNV, nv.HoTen, nv.Email, nv.SDT, nv.GioiTinh, nv.NgaySinh, nv.DiaChi,
            pb.TenPB, nv.ChucVu, km.DuongDanAnh
        FROM TaiKhoan tk
        JOIN NhanVien nv ON tk.MaNV = nv.MaNV
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat km ON nv.MaNV = km.MaNV
        WHERE tk.TenDangNhap = ?
    """, (username,))
    emp = cursor.fetchone()

    if not emp:
        conn.close()
        flash("❌ Không tìm thấy thông tin nhân viên!", "danger")
        return redirect(url_for("employee_dashboard"))

    columns = [col[0] for col in cursor.description]
    employee = dict(zip(columns, emp))

    # Ảnh đại diện
    avatar = employee.get("DuongDanAnh")
    if avatar and avatar.strip():
        avatar = avatar.replace("\\", "/")
        if not avatar.startswith("/"):
            avatar = f"/{avatar}"
        employee["AnhDaiDien"] = avatar
    else:
        employee["AnhDaiDien"] = "/photos/default.jpg"

    # Giới tính hiển thị
    gt = employee.get("GioiTinh")
    employee["GioiTinhText"] = "Nam" if gt == 1 else "Nữ" if gt == 0 else "Chưa cập nhật"

    # --- Nếu nhân viên gửi form cập nhật ---
    if request.method == "POST":
        hoten = request.form.get("HoTen", "").strip()
        email = request.form.get("Email", "").strip()
        sdt = request.form.get("SDT", "").strip()
        diachi = request.form.get("DiaChi", "").strip()
        ngaysinh = request.form.get("NgaySinh", "").strip() or None
        gioitinh_raw = request.form.get("GioiTinh", "").lower().strip()
        gioitinh = 1 if gioitinh_raw in ["1", "nam", "male", "true"] else 0
        file = request.files.get("avatar")

        try:
            cursor.execute("DISABLE TRIGGER trg_Check_QuanLyPhongBan ON PhongBan")

            # ✅ Cập nhật thông tin hồ sơ
            cursor.execute("""
                EXEC sp_UpdateEmployeeProfile ?, ?, ?, ?, ?, ?, ?
            """, (
                employee["MaNV"], hoten, email, sdt, gioitinh, ngaysinh, diachi
            ))

            cursor.execute("ENABLE TRIGGER trg_Check_QuanLyPhongBan ON PhongBan")

            # ✅ Cập nhật ảnh
            if file and file.filename:
                os.makedirs("photos", exist_ok=True)
                filename = f"{employee['MaNV']}.jpg"
                save_path = os.path.join("photos", filename)
                file.save(save_path)
                db_path = f"photos/{filename}"

                cursor.execute("""
                    MERGE KhuonMat AS target
                    USING (SELECT ? AS MaNV, ? AS DuongDanAnh) AS src
                    ON target.MaNV = src.MaNV
                    WHEN MATCHED THEN UPDATE SET target.DuongDanAnh = src.DuongDanAnh, target.TrangThai = 1
                    WHEN NOT MATCHED THEN INSERT (MaNV, DuongDanAnh, TrangThai) VALUES (src.MaNV, src.DuongDanAnh, 1);
                """, (employee["MaNV"], db_path))

            conn.commit()
            flash("✅ Cập nhật hồ sơ thành công!", "success")
            return redirect(url_for("employee_bp.employee_profile"))

        except Exception as e:
            conn.rollback()
            flash(f"❌ Lỗi khi cập nhật hồ sơ: {e}", "danger")

        finally:
            conn.close()

    conn.close()
    return render_template("edit_profile.html", employee=employee)

# ============================================================
# 📸 TRANG KHUÔN MẶT CỦA NHÂN VIÊN
# ============================================================
@employee_bp.route("/my_face")
@require_role("nhanvien")
def my_face():
    username = session.get("username")

    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🧩 Lấy thông tin nhân viên + ảnh đại diện (1 dòng)
    cursor.execute("""
        SELECT nv.HoTen, km.DuongDanAnh
        FROM NhanVien nv
        JOIN TaiKhoan tk ON tk.MaNV = nv.MaNV
        LEFT JOIN KhuonMat km ON nv.MaNV = km.MaNV AND km.TrangThai = 1
        WHERE tk.TenDangNhap = ?
    """, (username,))
    emp = cursor.fetchone()
    ho_ten, duongdananh = emp if emp else ("Không rõ", None)

    # ✅ Chuẩn hóa đường dẫn ảnh
    if duongdananh and duongdananh.strip():
        duongdananh = duongdananh.replace("\\", "/")
        if not duongdananh.startswith("/"):
            duongdananh = f"/{duongdananh}"
    else:
        duongdananh = "/photos/default.jpg"

    # 🧩 Lấy danh sách khuôn mặt (nếu nhân viên có nhiều bản ghi)
    cursor.execute("""
        SELECT nv.MaNV, nv.HoTen, pb.TenPB, k.FaceID, k.DuongDanAnh, 
               k.NgayDangKy, k.TrangThai
        FROM KhuonMat k
        JOIN NhanVien nv ON k.MaNV = nv.MaNV
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        JOIN TaiKhoan tk ON tk.MaNV = nv.MaNV
        WHERE tk.TenDangNhap = ?
    """, (username,))
    face_data = cursor.fetchall()
    conn.close()

    return render_template(
        "my_face.html",
        face_data=face_data,
        ho_ten=ho_ten,
        anh_nv=duongdananh
    )
# ============================================================
# 🗓️ TRANG LỊCH LÀM VIỆC CỦA NHÂN VIÊN
# ============================================================
@employee_bp.route("/my_schedule")
@require_role("nhanvien")
def employee_shifts():
    if "manv" not in session:
        return redirect(url_for("login"))

    ma_nv = session["manv"]
    username = session.get("username")

    conn = get_sql_connection()
    cursor = conn.cursor()

    # 🧩 Lấy thông tin nhân viên + phòng ban + ảnh khuôn mặt
    cursor.execute("""
        SELECT 
            nv.MaNV, 
            nv.HoTen, 
            nv.ChucVu, 
            pb.TenPB,
            k.DuongDanAnh
        FROM NhanVien nv
        JOIN TaiKhoan tk ON nv.MaNV = tk.MaNV
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat k ON nv.MaNV = k.MaNV AND k.TrangThai = 1
        WHERE tk.TenDangNhap = ?
    """, (username,))
    emp = cursor.fetchone()

    if not emp:
        conn.close()
        flash("❌ Không tìm thấy thông tin nhân viên!", "danger")
        return redirect(url_for("employee_bp.employee_dashboard"))

    ma_nv, ho_ten, chuc_vu, ten_pb, duongdananh = emp

    # ✅ Chuẩn hóa đường dẫn ảnh (ảnh nằm ngoài static)
    import os
    if duongdananh and duongdananh.strip():
        duongdananh = duongdananh.replace("\\", "/")
        file_name = os.path.basename(duongdananh)
        duongdananh = f"/photos/{file_name}"
    else:
        duongdananh = "/photos/default.jpg"

    # 🧩 Lấy danh sách lịch làm việc của nhân viên
    cursor.execute("""
        SELECT 
            llv.NgayLam,
            clv.TenCa,
            clv.GioBatDau,
            clv.GioKetThuc,
            pb.TenPB,
            llv.TrangThai
        FROM LichLamViec llv
        JOIN CaLamViec clv ON llv.MaCa = clv.MaCa
        JOIN NhanVien nv ON llv.MaNV = nv.MaNV
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        WHERE llv.MaNV = ? AND llv.DaXoa = 1
        ORDER BY llv.NgayLam DESC
    """, (ma_nv,))
    rows = cursor.fetchall()
    conn.close()

    # 🧩 Chuyển dữ liệu thành danh sách dict để dễ hiển thị
    schedules = []
    for row in rows:
        ngaylam, tenca, giobd, giokt, phongban, trangthai = row

        # Chuyển giờ dạng string hoặc datetime thành text
        try:
            thoi_gian = f"{str(giobd)[:5]} - {str(giokt)[:5]}" if giobd and giokt else "—"
        except Exception:
            thoi_gian = "—"

        # Chuyển trạng thái số sang chữ + CSS class
        if trangthai == 1:
            tt_text = "Đã hoàn thành"
            tt_class = "status-done"
        elif trangthai == 2:
            tt_text = "Vắng"
            tt_class = "status-absent"
        elif trangthai == 0:
            tt_text = "Chưa chấm công"
            tt_class = "status-pending"
        else:
            tt_text = "Đã lên lịch"
            tt_class = "status-upcoming"

        schedules.append({
            "NgayLam": ngaylam.strftime("%Y-%m-%d") if ngaylam else "",
            "TenCa": tenca or "—",
            "ThoiGian": thoi_gian,
            "PhongBan": phongban or ten_pb or "Chưa có",
            "TrangThai": tt_text,
            "TrangThaiClass": tt_class
        })

    # 🧩 Render ra giao diện
    return render_template(
        "employee_shifts.html",
        schedules=schedules,
        ho_ten=ho_ten,
        anh_nv=duongdananh
    )

# ============================================================
# 🕓 TRANG XEM LỊCH SỬ CHẤM CÔNG CỦA NHÂN VIÊN
# ============================================================
@employee_bp.route("/employee/attendance")
@require_role("nhanvien")
def employee_attendance():
    if "manv" not in session:
        return redirect(url_for("login"))

    ma_nv = session["manv"]
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT NgayChamCong, GioVao, GioRa, TrangThai
            FROM ChamCong
            WHERE MaNV = ?
            ORDER BY NgayChamCong DESC
        """, (ma_nv,))
        chamcong = [dict(zip([col[0] for col in cursor.description], r)) for r in cursor.fetchall()]
    except Exception as e:
        flash(f"❌ Lỗi khi tải lịch sử chấm công: {e}", "danger")
        chamcong = []
    finally:
        conn.close()

    return render_template("employee_attendance.html", chamcong=chamcong)


# ============================================================
# 💰 TRANG XEM LƯƠNG CỦA NHÂN VIÊN
# ============================================================
@employee_bp.route("/my_salary")
@require_role("nhanvien")
def my_salary():
    from datetime import datetime
    from core.salary_utils import tinh_luong_nv  # đảm bảo bạn đã tách hàm này ra module riêng

    username = session.get("username")
    conn = get_sql_connection()
    cursor = conn.cursor()
    now = datetime.now()
    thangnam = datetime(now.year, now.month, 1)

    # 🧩 Lấy thông tin nhân viên + ảnh khuôn mặt
    cursor.execute("""
        SELECT 
            nv.MaNV, 
            nv.HoTen, 
            nv.ChucVu, 
            pb.TenPB,
            k.DuongDanAnh
        FROM NhanVien nv
        JOIN TaiKhoan tk ON nv.MaNV = tk.MaNV
        LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
        LEFT JOIN KhuonMat k ON nv.MaNV = k.MaNV AND k.TrangThai = 1
        WHERE tk.TenDangNhap = ?
    """, (username,))
    emp = cursor.fetchone()

    if not emp:
        conn.close()
        flash("❌ Không tìm thấy thông tin nhân viên!", "danger")
        return redirect(url_for("employee_bp.employee_dashboard"))

    ma_nv, ho_ten, chuc_vu, ten_pb, anh_nv = emp

    # ✅ Chuẩn hóa ảnh
    if anh_nv and anh_nv.strip():
        anh_nv = anh_nv.replace("\\", "/")
        if not anh_nv.startswith("/"):
            anh_nv = f"/{anh_nv}"
    else:
        anh_nv = "/photos/default.jpg"

    # 🧩 Gọi hàm tính lương chi tiết (chỉ xem, không lưu DB)
    try:
        tong_gio, tong_tien, records = tinh_luong_nv(
            cursor, ma_nv, thangnam, "Xem lương cá nhân",
            save_to_db=False, return_detail=True
        )
    except Exception as e:
        flash(f"❌ Lỗi khi tính lương: {e}", "danger")
        tong_gio, tong_tien, records = 0, 0, []

    conn.close()

    # 🔹 Chuẩn hóa dữ liệu chi tiết lương
    salary_details = []
    for r in records:
        salary_details.append({
            "NgayLam": r.get("NgayChamCong"),
            "TenCa": r.get("Ca"),
            "GioBatDau": r.get("GioBatDau"),
            "GioKetThuc": r.get("GioKetThuc"),
            "GioVao": r.get("GioVao"),
            "GioRa": r.get("GioRa"),
            "SoGio": r.get("SoGio"),
            "HeSo": r.get("HeSo"),
            "ThanhTien": r.get("Tien"),
            "LyDo": r.get("LyDoTru"),
        })

    # 🧩 Gán biểu tượng chức vụ
    chucvu_lower = (chuc_vu or "").lower()
    if "trưởng phòng" in chucvu_lower:
        role_label, role_icon = "Trưởng phòng", "fa-star text-warning"
    elif "phó phòng" in chucvu_lower:
        role_label, role_icon = "Phó phòng", "fa-crown text-info"
    elif "thực tập" in chucvu_lower or "intern" in chucvu_lower:
        role_label, role_icon = "Thực tập sinh", "fa-user-graduate text-secondary"
    else:
        role_label, role_icon = "Nhân viên", "fa-user text-primary"

    # ✅ Render giao diện
    return render_template(
        "my_salary.html",
        emp=emp,
        salary_details=salary_details,
        tong_gio=tong_gio,
        tong_tien=tong_tien,
        role_label=role_label,
        role_icon=role_icon,
        current_month=now.month,
        current_year=now.year,
        ho_ten=ho_ten,
        anh_nv=anh_nv,
        now=now
    )
