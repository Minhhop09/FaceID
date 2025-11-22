# attendance_bp.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from core.db_utils import get_sql_connection
from core.decorators import require_role
<<<<<<< HEAD
import math
from flask import jsonify
from core.email_utils import notify_attendance, send_email_notification

# Import lại hàm record_attendance từ attendance_system
from routes.attendance_system import record_attendance

attendance_bp = Blueprint("attendance_bp", __name__)

@attendance_bp.route("/attendance_report", methods=["GET"])
@require_role("admin", "hr", "quanlyphongban")
def attendance_report():
    """
    ✅ BÁO CÁO CHẤM CÔNG — FINAL FIXED v28
    ------------------------------------------------------------------
    ✔ Hiển thị:
        - Nhân viên có chấm công (có bản ghi ChamCong)
        - Ca đã kết thúc hoặc đã qua ngày (tự động hiện Vắng)
        - Nghỉ phép đã duyệt (DonNghiPhep.TrangThaiDuyet = 'Đã duyệt')
    ❌ Không hiển thị:
        - Ca chưa diễn ra (tương lai)
        - Ca đang diễn ra mà chưa có chấm hoặc cập nhật
    ✔ “Vắng mặt” tự động hiển thị khi hết ca mà chưa chấm
    ------------------------------------------------------------------
    """
    from datetime import datetime
    conn = get_sql_connection()
    cursor = conn.cursor()

    role = session.get("role")
    username = session.get("username")

    # ============================================================
    # 1️⃣ LỌC THÁNG / NĂM
    # ============================================================
    month = request.args.get("month")
    year = request.args.get("year")
    filter_query = "WHERE LLV.DaXoa = 1"
    params = []

    if month and year:
        filter_query += " AND MONTH(LLV.NgayLam)=? AND YEAR(LLV.NgayLam)=?"
        params.extend([month, year])
    elif year:
        filter_query += " AND YEAR(LLV.NgayLam)=?"
        params.append(year)

    # ============================================================
    # 2️⃣ LỌC THEO PHÒNG BAN (nếu là QLPB)
    # ============================================================
=======

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
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
    if role == "quanlyphongban":
        cursor.execute("""
            SELECT nv.MaPB
            FROM NhanVien nv
            JOIN TaiKhoan tk ON nv.MaNV = tk.MaNV
            WHERE tk.TenDangNhap = ?
        """, (username,))
        row = cursor.fetchone()
<<<<<<< HEAD
        if row:
            filter_query += " AND PB.MaPB = ?"
            params.append(row[0])

    # ============================================================
    # 3️⃣ TRUY VẤN CHÍNH
    # ============================================================
    cursor.execute(f"""
        SELECT
            LLV.MaLLV,
            NV.MaNV,
            NV.HoTen,
            PB.TenPB AS PhongBan,
            CLV.MaCa,
            CLV.TenCa AS CaLam,
            FORMAT(CLV.GioBatDau, 'HH:mm') AS GioBatDau,
            FORMAT(CLV.GioKetThuc, 'HH:mm') AS GioKetThuc,
            FORMAT(LLV.NgayLam, 'yyyy-MM-dd') AS NgayChamCong,
            FORMAT(CC.GioVao, 'HH:mm') AS GioVao,
            FORMAT(CC.GioRa, 'HH:mm') AS GioRa,

            -- 🕒 Số giờ làm
            CASE
                WHEN CC.GioVao IS NOT NULL AND CC.GioRa IS NOT NULL THEN
                    ROUND(
                        (
                            CASE 
                                WHEN CONVERT(TIME, CC.GioRa) >= CONVERT(TIME, CC.GioVao)
                                    THEN DATEDIFF(MINUTE, CONVERT(TIME, CC.GioVao), CONVERT(TIME, CC.GioRa))
                                ELSE DATEDIFF(MINUTE, CONVERT(TIME, CC.GioVao), CONVERT(TIME, CC.GioRa)) + 1440
                            END
                        ) / 60.0, 2
                    )
                ELSE 0
            END AS GioLam,

            CC.MaChamCong,

            -- 🔹 Mã trạng thái tổng hợp (ưu tiên theo thứ tự logic)
            CASE
                WHEN DNP.MaDon IS NOT NULL THEN 3                                 -- Nghỉ phép được duyệt
                WHEN CC.TrangThai IN (0,1,2,3) THEN CC.TrangThai                  -- Có bản ghi chấm công hoặc cập nhật
                WHEN CC.MaChamCong IS NULL 
                     AND (
                         LLV.NgayLam < CAST(GETDATE() AS DATE)                    -- Ngày cũ
                         OR (LLV.NgayLam = CAST(GETDATE() AS DATE)
                             AND CONVERT(TIME, GETDATE()) > CLV.GioKetThuc)       -- Hôm nay nhưng đã qua giờ kết thúc
                     )
                THEN 0                                                            -- Vắng mặt
                ELSE NULL
            END AS TrangThai,

            -- 🔹 Text hiển thị trạng thái
            CASE 
                WHEN DNP.MaDon IS NOT NULL THEN N'Nghỉ phép'
                WHEN CC.TrangThai = 1 THEN N'Đúng giờ'
                WHEN CC.TrangThai = 2 THEN N'Đi muộn'
                WHEN CC.TrangThai = 0 THEN N'Vắng mặt'
                WHEN CC.TrangThai = 3 THEN N'Nghỉ phép'
                WHEN (CC.MaChamCong IS NULL 
                      AND (
                          LLV.NgayLam < CAST(GETDATE() AS DATE)
                          OR (LLV.NgayLam = CAST(GETDATE() AS DATE)
                              AND CONVERT(TIME, GETDATE()) > CLV.GioKetThuc)
                      )) THEN N'Vắng mặt'
                ELSE N'Không xác định'
            END AS TrangThaiText

        FROM LichLamViec LLV
        JOIN NhanVien NV ON LLV.MaNV = NV.MaNV
        JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        JOIN CaLamViec CLV ON LLV.MaCa = CLV.MaCa
        LEFT JOIN ChamCong CC 
            ON CC.MaNV = LLV.MaNV 
           AND CONVERT(DATE, CC.NgayChamCong) = CONVERT(DATE, LLV.NgayLam)
           AND CC.MaCa = LLV.MaCa
           AND CC.DaXoa = 1
        LEFT JOIN DonNghiPhep DNP 
            ON DNP.MaNV = LLV.MaNV
        AND DNP.TrangThaiDuyet = N'Đã duyệt' 
        AND DNP.DaXoa = 0
        AND EXISTS (
            SELECT 1 
            FROM DonNghiPhep_CaLam DN
            WHERE DN.MaDon = DNP.MaDon 
                AND DN.MaCa = LLV.MaCa
                AND CONVERT(date, DN.NgayNghi) = CONVERT(date, LLV.NgayLam)
        )


        {filter_query}
          AND (
              -- 🟢 Có chấm công
              CC.MaChamCong IS NOT NULL
              -- 🟢 Có cập nhật thủ công (vắng, phép)
              OR CC.TrangThai IN (0,3)
              -- 🟢 Đã qua giờ kết thúc (hôm nay hoặc ngày cũ)
              OR (
                  LLV.NgayLam < CAST(GETDATE() AS DATE)
                  OR (LLV.NgayLam = CAST(GETDATE() AS DATE)
                      AND CONVERT(TIME, GETDATE()) > CLV.GioKetThuc)
              )
          )
        ORDER BY LLV.NgayLam DESC, NV.HoTen, CLV.TenCa
    """, params)

    # ============================================================
    # 4️⃣ XỬ LÝ KẾT QUẢ
    # ============================================================
    columns = [c[0] for c in cursor.description]
    records = [dict(zip(columns, row)) for row in cursor.fetchall()]
    conn.close()

    # ============================================================
    # 5️⃣ THỐNG KÊ
    # ============================================================
    total_records = len(records)
    total_on_time = sum(1 for r in records if r["TrangThai"] == 1)
    total_late = sum(1 for r in records if r["TrangThai"] == 2)
    total_leave = sum(1 for r in records if r["TrangThai"] == 3)
    total_absent = sum(1 for r in records if r["TrangThai"] == 0)
    attendance_rate = (
        (total_on_time + total_late) / total_records * 100 if total_records else 0
    )

    # ============================================================
    # 6️⃣ TRẢ VỀ TEMPLATE
    # ============================================================
    template_name = {
        "admin": "attendance_report.html",
        "hr": "hr_attendance_report.html",
        "quanlyphongban": "qlpb_attendance_report.html",
    }.get(role, "attendance_report.html")
=======
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
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c

    return render_template(
        template_name,
        records=records,
        total_records=total_records,
        total_on_time=total_on_time,
        total_late=total_late,
<<<<<<< HEAD
        total_leave=total_leave,
=======
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
        total_absent=total_absent,
        attendance_rate=attendance_rate,
        month=month,
        year=year,
<<<<<<< HEAD
        role=role,
    )

# ============================================================
# ➕ THÊM CHẤM CÔNG (Admin / HR)
# ============================================================
=======
        role=role
    )

# THÊM CHẤM CÔNG

>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
@attendance_bp.route("/attendance/add", methods=["GET", "POST"])
@require_role("admin", "hr")
def add_attendance():
    conn = get_sql_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        try:
            MaNV = request.form["MaNV"]
            NgayChamCong = request.form["Ngay"]
<<<<<<< HEAD
            GioVao = request.form.get("GioVao") or None
            GioRa = request.form.get("GioRa") or None
            MaCa = request.form.get("MaCa") or None
            TrangThai = int(request.form.get("TrangThai", 1))  # Mặc định 1: Đúng giờ

            # --- 1️⃣ Kiểm tra trùng bản ghi cùng ngày và ca ---
            cursor.execute("""
                SELECT 1 FROM ChamCong
                WHERE MaNV = ? AND NgayChamCong = ? AND MaCa = ?
            """, (MaNV, NgayChamCong, MaCa))
            if cursor.fetchone():
                flash("⚠️ Nhân viên này đã có bản ghi chấm công trong ca này!", "warning")
                conn.close()
                return redirect(url_for("attendance_bp.attendance_report"))

            # --- 2️⃣ Tự động xác định đúng giờ / đi muộn ---
            if GioVao and MaCa:
                cursor.execute("SELECT GioBatDau FROM CaLamViec WHERE MaCa = ?", (MaCa,))
                ca_info = cursor.fetchone()
                if ca_info:
                    gio_bat_dau = ca_info[0]
                    try:
                        gio_vao_dt = datetime.strptime(GioVao, "%H:%M").time()
                        if gio_vao_dt > gio_bat_dau:  # Vào muộn
                            TrangThai = 2  # Đi muộn
                        else:
                            TrangThai = 1  # Đúng giờ
                    except Exception:
                        pass  # Nếu lỗi định dạng thì giữ nguyên trạng thái form

            # --- 3️⃣ Chèn bản ghi mới ---
            cursor.execute("""
                INSERT INTO ChamCong (MaNV, NgayChamCong, GioVao, GioRa, TrangThai, MaCa, DaXoa)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (MaNV, NgayChamCong, GioVao, GioRa, TrangThai, MaCa))

            conn.commit()
            flash("✅ Đã thêm bản ghi chấm công mới!", "success")
            return redirect(url_for("attendance_bp.attendance_report"))

        except Exception as e:
            conn.rollback()
            flash(f"❌ Lỗi khi thêm chấm công: {e}", "danger")
        finally:
            conn.close()

    # --- 4️⃣ Danh sách nhân viên đang hoạt động ---
    cursor.execute("SELECT MaNV, HoTen FROM NhanVien WHERE TrangThai = 1 ORDER BY HoTen")
    employees = cursor.fetchall()

    # --- 5️⃣ Danh sách ca làm việc ---
=======
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

>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
    cursor.execute("""
        SELECT MaCa, TenCa, 
               FORMAT(GioBatDau, 'HH:mm') + N' - ' + FORMAT(GioKetThuc, 'HH:mm') AS KhungGio
        FROM CaLamViec
        WHERE TrangThai = 1
        ORDER BY MaCa
    """)
    shifts = cursor.fetchall()
    conn.close()

<<<<<<< HEAD
    return render_template("attendance_add.html", employees=employees, shifts=shifts)

# ============================================================
# ✏️ SỬA CHẤM CÔNG (Admin / HR) — FINAL FIXED v8
# ✅ Tự động nhận biết LLV/ChamCong + xóa bản vắng khi thêm chấm công
# ============================================================
# ============================================================
# ✏️ SỬA CHẤM CÔNG (Admin / HR) — FINAL FIXED v10
# ✅ Nếu là ca "vắng" → thêm bản chấm công & cập nhật LLV thành "đúng giờ"
# ============================================================
# ============================================================
# ✏️ SỬA / THÊM CHẤM CÔNG — FINAL FIXED v11 (có phân biệt type)
# ✅ type='cc' → sửa chấm công có sẵn
# ✅ type='llv' → thêm chấm công mới từ lịch làm việc (vắng/NG)
# ============================================================
@attendance_bp.route("/attendance/edit/<type>/<int:id>", methods=["GET", "POST"])
@require_role("admin", "hr")
def edit_attendance(type, id):
    from datetime import datetime
    conn = None
    cursor = None
    role = session.get("role", "admin")

    try:
        conn = get_sql_connection()
        cursor = conn.cursor()

        # ✅ Phân loại rõ ràng
        is_chamcong = (type == "cc")
        is_lichlamviec = (type == "llv")

        if not is_chamcong and not is_lichlamviec:
            flash("❌ Loại bản ghi không hợp lệ!", "danger")
            return redirect(url_for("attendance_bp.attendance_report"))

        # ============================================================
        # 2️⃣ Xử lý lưu (POST)
        # ============================================================
        if request.method == "POST":
            GioVao = request.form.get("GioVao") or None
            GioRa = request.form.get("GioRa") or None
            TrangThai = int(request.form.get("TrangThai", 1))
            MaCa = request.form.get("MaCa") or None
            MaNV = request.form.get("MaNV")
            NgayChamCong = request.form.get("NgayChamCong")

            # 🕓 Tự xác định đúng giờ / đi muộn
            if MaCa and GioVao:
                cursor.execute("SELECT GioBatDau FROM CaLamViec WHERE MaCa = ?", (MaCa,))
                ca_info = cursor.fetchone()
                if ca_info:
                    try:
                        gio_bat_dau = ca_info[0]
                        gio_vao_dt = datetime.strptime(GioVao, "%H:%M").time()
                        TrangThai = 2 if gio_vao_dt > gio_bat_dau else 1
                    except Exception:
                        pass

            # 🔹 Nếu là ChamCong → cập nhật
            if is_chamcong:
                cursor.execute("""
                    UPDATE ChamCong
                    SET GioVao=?, GioRa=?, TrangThai=?, MaCa=?, DaXoa=1
                    WHERE MaChamCong=?;
                """, (GioVao, GioRa, TrangThai, MaCa, id))
                flash("✅ Đã cập nhật bản ghi chấm công!", "success")

            # 🔹 Nếu là LichLamViec → thêm mới bản chấm công
            else:
                # 1️⃣ Ẩn bản ChamCong “vắng” cũ (nếu có)
                cursor.execute("""
                    UPDATE ChamCong
                    SET DaXoa=0
                    WHERE MaNV=? 
                      AND CONVERT(date, NgayChamCong)=CONVERT(date, ?)
                      AND MaCa=? 
                      AND TrangThai=0;
                """, (MaNV, NgayChamCong, MaCa))

                # 2️⃣ Thêm bản chấm công mới
                cursor.execute("""
                    INSERT INTO ChamCong (MaNV, NgayChamCong, GioVao, GioRa, TrangThai, MaCa, DaXoa)
                    VALUES (?, ?, ?, ?, ?, ?, 1);
                """, (MaNV, NgayChamCong, GioVao, GioRa, TrangThai, MaCa))

                # 3️⃣ Ẩn dòng “vắng” tương ứng trong LichLamViec
                cursor.execute("""
                    UPDATE LichLamViec
                    SET DaXoa=0
                    WHERE MaNV=? 
                      AND CONVERT(date, NgayLam)=CONVERT(date, ?)
                      AND MaCa=? 
                      AND (TrangThai=0 OR TrangThai IS NULL);
                """, (MaNV, NgayChamCong, MaCa))

                flash("🆕 Đã thêm bản ghi chấm công và ẩn dòng 'vắng' cũ!", "success")

            conn.commit()
            return redirect(url_for("attendance_bp.attendance_report"))

        # ============================================================
        # 3️⃣ Mở form sửa (GET)
        # ============================================================
        if is_chamcong:
            cursor.execute("""
                SELECT 
                    CC.MaChamCong, NV.MaNV, NV.HoTen, PB.TenPB,
                    FORMAT(CC.NgayChamCong, 'yyyy-MM-dd') AS NgayChamCong,
                    FORMAT(CC.GioVao, 'HH:mm') AS GioVao,
                    FORMAT(CC.GioRa, 'HH:mm') AS GioRa,
                    CC.TrangThai, CC.MaCa,
                    KM.DuongDanAnh
                FROM ChamCong CC
                JOIN NhanVien NV ON CC.MaNV = NV.MaNV
                LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
                LEFT JOIN KhuonMat KM ON NV.MaNV = KM.MaNV
                WHERE CC.MaChamCong = ?
            """, (id,))
        else:
            cursor.execute("""
                SELECT 
                    NULL AS MaChamCong, NV.MaNV, NV.HoTen, PB.TenPB,
                    FORMAT(LLV.NgayLam, 'yyyy-MM-dd') AS NgayChamCong,
                    NULL AS GioVao, NULL AS GioRa,
                    LLV.TrangThai, LLV.MaCa,
                    KM.DuongDanAnh
                FROM LichLamViec LLV
                JOIN NhanVien NV ON NV.MaNV = LLV.MaNV
                LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
                LEFT JOIN KhuonMat KM ON NV.MaNV = KM.MaNV
                WHERE LLV.MaLLV = ?
            """, (id,))

        row = cursor.fetchone()
        if not row:
            flash("❌ Không tìm thấy dữ liệu phù hợp.", "danger")
            return redirect(url_for("attendance_bp.attendance_report"))

        # Mapping dữ liệu
        record_cols = [
            "MaChamCong", "MaNV", "HoTen", "TenPB",
            "NgayChamCong", "GioVao", "GioRa", "TrangThai",
            "MaCa", "DuongDanAnh"
        ]
        record = dict(zip(record_cols, row))
        avatar_path = record.get("DuongDanAnh")
        record["Avatar"] = (
            "/" + avatar_path.replace("\\", "/")
            if avatar_path else "/static/photos/default.jpg"
        )

        # Danh sách ca
        cursor.execute("""
            SELECT MaCa, TenCa,
                   FORMAT(GioBatDau, 'HH:mm') + N' - ' + FORMAT(GioKetThuc, 'HH:mm') AS KhungGio
            FROM CaLamViec
            WHERE TrangThai = 1
            ORDER BY MaCa
        """)
        shifts = cursor.fetchall()
        shift_list = [{"MaCa": s[0], "TenCa": s[1], "KhungGio": s[2]} for s in shifts]

        template_name = "hr_attendance_edit.html" if role == "hr" else "attendance_edit.html"
        return render_template(template_name, record=record, shifts=shift_list)

    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"❌ Lỗi khi xử lý chấm công: {e}", "danger")
        return redirect(url_for("attendance_bp.attendance_report"))

    finally:
        try:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        except Exception as e:
            print("[WARN] Không thể đóng kết nối:", e)

# ============================================================
# 🗑️ XÓA MỀM 1 BẢN GHI CHẤM CÔNG
# ============================================================
=======
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

>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
@attendance_bp.route("/attendance/delete/<int:id>", methods=["POST"])
@require_role("admin", "hr")
def delete_attendance(id):
    conn = get_sql_connection()
    cursor = conn.cursor()
<<<<<<< HEAD
    username = session.get("username", "Hệ thống")

    try:
        # ✅ Đặt DaXoa = 0 để ẩn bản ghi (xóa mềm)
        cursor.execute("UPDATE ChamCong SET DaXoa = 0 WHERE MaChamCong = ?", (id,))

        # ✅ Ghi vào lịch sử thay đổi
=======
    role = session.get("role", "admin")
    username = session.get("username", "Hệ thống")

    try:
        cursor.execute("UPDATE ChamCong SET DaXoa = 0 WHERE MaChamCong = ?", (id,))
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("ChamCong", id, "Xóa mềm", "DaXoa", "1", "0", username))

        conn.commit()
<<<<<<< HEAD
        flash("🗑️ Đã xóa mềm bản ghi chấm công và ghi vào lịch sử!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa mềm bản ghi chấm công: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("attendance_bp.attendance_report"))


# ============================================================
# 🗑️ XÓA MỀM NHIỀU BẢN GHI CHẤM CÔNG
# ============================================================
=======
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

>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
@attendance_bp.route("/attendance/delete_multiple", methods=["POST"])
@require_role("admin", "hr")
def delete_multiple_attendance():
    selected_ids = request.form.getlist("selected_attendance")
    if not selected_ids:
<<<<<<< HEAD
        flash("⚠️ Chưa chọn bản ghi chấm công nào để xóa!", "warning")
=======
        flash("Chưa chọn bản ghi chấm công nào để xóa!", "warning")
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
        return redirect(url_for("attendance_bp.attendance_report"))

    conn = get_sql_connection()
    cursor = conn.cursor()
<<<<<<< HEAD
=======
    role = session.get("role", "admin")
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
    username = session.get("username", "Hệ thống")

    try:
        for ma_cc in selected_ids:
<<<<<<< HEAD
            # ✅ Đặt DaXoa = 0 để ẩn bản ghi (xóa mềm)
            cursor.execute("UPDATE ChamCong SET DaXoa = 0 WHERE MaChamCong = ?", (ma_cc,))
            
            # ✅ Ghi log lịch sử thay đổi
=======
            cursor.execute("UPDATE ChamCong SET DaXoa = 0 WHERE MaChamCong = ?", (ma_cc,))
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, ("ChamCong", ma_cc, "Xóa mềm", "DaXoa", "1", "0", username))

        conn.commit()
<<<<<<< HEAD
        flash(f"🗑️ Đã xóa mềm {len(selected_ids)} bản ghi chấm công!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi xóa nhiều bản ghi chấm công: {e}", "danger")
=======
        flash(f"Đã xóa mềm {len(selected_ids)} bản ghi chấm công!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"Lỗi khi xóa nhiều bản ghi chấm công: {e}", "danger")
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
    finally:
        conn.close()

    return redirect(url_for("attendance_bp.attendance_report"))

<<<<<<< HEAD
# ============================================================
# ♻️ KHÔI PHỤC 1 BẢN GHI CHẤM CÔNG
# ============================================================
@attendance_bp.route("/attendance/restore/<int:id>", methods=["POST"])
@require_role("admin", "hr")
def restore_attendance(id):
    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")

    try:
        # ✅ Đặt lại DaXoa = 1 để khôi phục (hiển thị lại bản ghi)
        cursor.execute("UPDATE ChamCong SET DaXoa = 1 WHERE MaChamCong = ?", (id,))
        
        # ✅ Ghi log lịch sử thay đổi
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
        """, ("ChamCong", id, "Khôi phục", "DaXoa", "0", "1", username))

        conn.commit()
        flash("♻️ Đã khôi phục bản ghi chấm công!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục bản ghi: {e}", "danger")
=======
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
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
    finally:
        conn.close()

    return redirect(url_for("attendance_bp.deleted_attendance"))

<<<<<<< HEAD

# ============================================================
# ♻️ KHÔI PHỤC NHIỀU BẢN GHI CHẤM CÔNG
# ============================================================
@attendance_bp.route("/attendance/restore_multiple", methods=["POST"])
@require_role("admin", "hr")
=======
# KHÔI PHỤC NHIỀU BẢN GHI CHẤM CÔNG

@attendance_bp.route("/attendance/restore_multiple", methods=["POST"])
@require_role("admin")
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
def restore_multiple_attendance():
    selected_ids = request.form.getlist("selected_ids")

    if not selected_ids:
<<<<<<< HEAD
        flash("⚠️ Chưa chọn bản ghi nào để khôi phục!", "warning")
=======
        flash("Chưa chọn bản ghi nào để khôi phục!", "warning")
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
        return redirect(url_for("attendance_bp.deleted_attendance"))

    conn = get_sql_connection()
    cursor = conn.cursor()
<<<<<<< HEAD
    username = session.get("username", "Hệ thống")

    try:
        for ma_cc in selected_ids:
            # ✅ Đặt lại DaXoa = 1 để khôi phục (hiển thị lại)
            cursor.execute("UPDATE ChamCong SET DaXoa = 1 WHERE MaChamCong = ?", (ma_cc,))
            
            # ✅ Ghi log lịch sử thay đổi
=======

    try:
        username = session.get("username", "Hệ thống")
        for ma_cc in selected_ids:
            cursor.execute("UPDATE ChamCong SET DaXoa = 1 WHERE MaChamCong = ?", (ma_cc,))
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?)
            """, ("ChamCong", ma_cc, "Khôi phục", "DaXoa", "0", "1", username))

        conn.commit()
<<<<<<< HEAD
        flash(f"♻️ Đã khôi phục {len(selected_ids)} bản ghi chấm công!", "success")

    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi khôi phục nhiều bản ghi: {e}", "danger")
=======
        flash(f"Đã khôi phục {len(selected_ids)} bản ghi chấm công!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Lỗi khi khôi phục: {e}", "danger")
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
    finally:
        conn.close()

    return redirect(url_for("attendance_bp.deleted_attendance"))

<<<<<<< HEAD
# ============================================================
# 🗑️ DANH SÁCH CHẤM CÔNG ĐÃ XÓA (Admin / HR)
# ============================================================
@attendance_bp.route("/attendance/deleted")
@require_role("admin", "hr")
=======
# DANH SÁCH CHẤM CÔNG ĐÃ XÓA

@attendance_bp.route("/attendance/deleted")
@require_role("admin")
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
def deleted_attendance():
    from datetime import datetime, time
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
<<<<<<< HEAD
        # ✅ Lấy các bản ghi đã xóa mềm (DaXoa = 0)
        cursor.execute("""
            SELECT 
                cc.MaChamCong,
                nv.MaNV,
=======
        cursor.execute("""
            SELECT 
                cc.MaChamCong,
                ISNULL(cc.MaNV, nv.MaNV) AS MaNV,
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
                nv.HoTen,
                pb.TenPB,
                clv.TenCa,
                cc.NgayChamCong,
                cc.GioVao,
                cc.GioRa,
                cc.TrangThai
            FROM ChamCong cc
<<<<<<< HEAD
            LEFT JOIN NhanVien nv ON cc.MaNV = nv.MaNV
=======
            JOIN NhanVien nv ON cc.MaNV = nv.MaNV
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
            LEFT JOIN PhongBan pb ON nv.MaPB = pb.MaPB
            LEFT JOIN CaLamViec clv ON cc.MaCa = clv.MaCa
            WHERE cc.DaXoa = 0
            ORDER BY cc.NgayChamCong DESC
        """)
        rows = cursor.fetchall()

<<<<<<< HEAD
        # Hàm chuẩn hóa giờ hiển thị
=======
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
        def format_time(value):
            if not value:
                return "—"
            if isinstance(value, (datetime, time)):
<<<<<<< HEAD
                return value.strftime("%H:%M")
=======
                return value.strftime("%H:%M:%S")
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
            val = str(value)
            if " " in val:
                val = val.split(" ")[-1]
            return val.replace("1900-01-01", "").strip() or "—"

        deleted_attendance = []
<<<<<<< HEAD
        for ma_cc, ma_nv, ho_ten, ten_pb, ten_ca, ngay, gio_vao, gio_ra, trang_thai in rows:
            gio_vao_txt, gio_ra_txt = format_time(gio_vao), format_time(gio_ra)
            trang_thai = int(trang_thai or 0)

            # ✅ Chuẩn hóa trạng thái 1–4 theo hệ thống
=======
        for ma_cham_cong, ma_nv, ho_ten, ten_pb, ten_ca, ngay, gio_vao, gio_ra, trang_thai in rows:
            gio_vao_txt, gio_ra_txt = format_time(gio_vao), format_time(gio_ra)
            trang_thai = int(trang_thai or 0)
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
            if trang_thai == 1:
                status_text, status_class = "Đúng giờ", "bg-success"
            elif trang_thai == 2:
                status_text, status_class = "Đi muộn", "bg-warning text-dark"
<<<<<<< HEAD
            elif trang_thai == 3:
                status_text, status_class = "Nghỉ phép", "bg-info text-dark"
            elif trang_thai == 4:
=======
            elif trang_thai == 0:
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
                status_text, status_class = "Vắng", "bg-danger"
            else:
                status_text, status_class = "Không xác định", "bg-secondary"

            deleted_attendance.append({
<<<<<<< HEAD
                "MaChamCong": str(ma_cc),
                "MaNV": ma_nv or "—",
=======
                "MaChamCong": str(ma_cham_cong),
                "MaNV": str(ma_nv) if ma_nv else "—",
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
                "HoTen": ho_ten or "—",
                "TenPB": ten_pb or "—",
                "TenCa": ten_ca or "—",
                "NgayChamCong": (
                    ngay.strftime("%Y-%m-%d") if isinstance(ngay, datetime)
<<<<<<< HEAD
                    else str(ngay)[:10] if ngay else "—"
=======
                    else str(ngay)[:10] if ngay else ""
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
                ),
                "GioVao": gio_vao_txt,
                "GioRa": gio_ra_txt,
                "TrangThai": trang_thai,
                "TrangThaiText": status_text,
                "StatusClass": status_class
            })

    except Exception as e:
<<<<<<< HEAD
        flash(f"❌ Lỗi khi tải danh sách chấm công đã xóa: {e}", "danger")
=======
        flash(f"Lỗi khi tải danh sách chấm công đã xóa: {e}", "error")
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
        deleted_attendance = []
    finally:
        conn.close()

<<<<<<< HEAD
    # ✅ Trả về template chung “deleted_records.html” (tab attendance)
=======
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
    return render_template(
        "deleted_records.html",
        active_tab="attendance",
        deleted_attendance=deleted_attendance
    )
<<<<<<< HEAD
# ============================================================
# 🧾 QUẢN LÝ NGHỈ PHÉP (dành cho HR)
# ============================================================
@attendance_bp.route("/attendance/leave_approval")
@require_role("hr")
def hr_leave_approval():
    """
    Trang HR duyệt đơn nghỉ phép.
    ✅ Hiển thị danh sách đơn nghỉ phép (lấy chi tiết ngày-ca từ DonNghiPhep_CaLam)
    ✅ Cho phép lọc theo trạng thái (Tất cả / Chờ duyệt / Đã duyệt / Từ chối)
    """
    from datetime import date
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # 🟣 1️⃣ Đếm số đơn chờ duyệt
        cursor.execute("""
            SELECT COUNT(*) 
            FROM DonNghiPhep
            WHERE TrangThaiDuyet = N'Chờ duyệt' AND (DaXoa = 0 OR DaXoa IS NULL)
        """)
        pending_count = cursor.fetchone()[0]

        # 🔍 2️⃣ Tham số lọc trạng thái
        trang_thai = request.args.get("status", "").strip()

        # 🟦 3️⃣ Lấy danh sách đơn nghỉ phép
        query = """
            SELECT 
                D.MaDon, D.MaNV, NV.HoTen,
                CONVERT(varchar, D.TuNgay, 23) AS TuNgay,
                CONVERT(varchar, D.DenNgay, 23) AS DenNgay,
                D.LyDo, D.LoaiNghi, D.TrangThaiDuyet,
                ISNULL(D.NguoiDuyet, '-') AS NguoiDuyet,
                ISNULL(CONVERT(varchar, D.NgayDuyet, 23), '-') AS NgayDuyet,
                ISNULL(CONVERT(varchar, D.NgayTao, 23), '-') AS NgayGui,
                ISNULL(D.GhiChu, '') AS GhiChu
            FROM DonNghiPhep D
            LEFT JOIN NhanVien NV ON NV.MaNV = D.MaNV
            WHERE (D.DaXoa = 0 OR D.DaXoa IS NULL)
        """
        params = []
        if trang_thai and trang_thai != "Tất cả":
            query += " AND D.TrangThaiDuyet = ?"
            params.append(trang_thai)

        query += " ORDER BY D.NgayTao DESC"

        cursor.execute(query, params)
        cols = [c[0] for c in cursor.description]
        don_list = [dict(zip(cols, row)) for row in cursor.fetchall()]

        # 🟨 4️⃣ Lấy chi tiết ngày–ca của từng đơn
        cursor.execute("""
            SELECT 
                C.MaDon,
                CONVERT(varchar, C.NgayNghi, 23) AS NgayNghi,
                C.MaCa,
                CLV.TenCa
            FROM DonNghiPhep_CaLam C
            JOIN CaLamViec CLV ON C.MaCa = CLV.MaCa
        """)
        cols2 = [c[0] for c in cursor.description]
        chitiet_list = [dict(zip(cols2, r)) for r in cursor.fetchall()]

        # 🟩 Gom chi tiết theo từng đơn
        for don in don_list:
            chi_tiet = [ct for ct in chitiet_list if ct["MaDon"] == don["MaDon"]]
            if chi_tiet:
                don["ChiTietCa"] = [
                    f"{ct['NgayNghi']} – {ct['TenCa']}" for ct in chi_tiet
                ]
            else:
                don["ChiTietCa"] = ["(Không có dữ liệu)"]

            # 🟢 Thêm class hiển thị trạng thái
            tt = don.get("TrangThaiDuyet", "")
            if tt == "Chờ duyệt":
                don["StatusClass"], don["StatusIcon"] = "bg-warning text-dark", "fa-clock"
            elif tt == "Đã duyệt":
                don["StatusClass"], don["StatusIcon"] = "bg-success", "fa-check-circle"
            elif tt == "Từ chối":
                don["StatusClass"], don["StatusIcon"] = "bg-danger", "fa-times-circle"
            else:
                don["StatusClass"], don["StatusIcon"] = "bg-secondary text-light", "fa-question-circle"

    except Exception as e:
        flash(f"❌ Lỗi khi tải danh sách đơn nghỉ phép: {e}", "danger")
        don_list, pending_count = [], 0
    finally:
        conn.close()

    return render_template(
        "hr_leave_approval.html",
        don_list=don_list,
        today=date.today().isoformat(),
        selected_status=trang_thai or "Tất cả",
        pending_count=pending_count
    )
# ============================================================
# ✅ DUYỆT / TỪ CHỐI / THU HỒI ĐƠN NGHỈ PHÉP — FINAL FIXED v4.5
# ============================================================
@attendance_bp.route("/attendance/approve_leave/<ma_don>/<action>", methods=["POST"])
@require_role("hr")
def approve_leave(ma_don, action):
    """
    HR duyệt, từ chối hoặc thu hồi đơn nghỉ phép.
    ------------------------------------------------------------
    - approve → LLV.TrangThai = 3, ChamCong.TrangThai = 3, trừ phép
    - reject  → Không đổi LLV/ChamCong, không trừ phép
    - restore → LLV.TrangThai = 0, ChamCong.TrangThai = NULL, hoàn lại phép
    ------------------------------------------------------------
    Có gửi email HTML thông báo và ghi log vào LichSuEmail.
    """
    from flask import jsonify, current_app
    from datetime import datetime
    from threading import Thread
    from flask_mail import Mail, Message

    conn = get_sql_connection()
    cursor = conn.cursor()
    nguoi_duyet = session.get("username", "HR")
    ly_do_tu_choi = (request.form.get("ly_do") or "").strip()
    action = (action or "").lower()

    try:
        # ============================================================
        # 1️⃣ Lấy thông tin đơn nghỉ phép + chi tiết ca/ngày
        # ============================================================
        cursor.execute("""
            SELECT MaNV, TuNgay, DenNgay, TrangThaiDuyet
            FROM DonNghiPhep
            WHERE MaDon = ? AND (DaXoa = 0 OR DaXoa IS NULL)
        """, (ma_don,))
        info = cursor.fetchone()
        if not info:
            return jsonify({"success": False, "message": "❌ Không tìm thấy đơn nghỉ phép."})

        ma_nv, tu_ngay, den_ngay, trang_thai_hien_tai = info

        cursor.execute("""
            SELECT MaCa, CONVERT(date, NgayNghi)
            FROM DonNghiPhep_CaLam
            WHERE MaDon = ?
        """, (ma_don,))
        ca_list = cursor.fetchall()
        if not ca_list:
            return jsonify({"success": False, "message": "❌ Đơn chưa chọn ca nào."})

        so_ca_nghi = len(ca_list)

        # ============================================================
        # 2️⃣ Cập nhật trạng thái đơn nghỉ phép
        # ============================================================
        trang_thai_text = {
            "approve": "Đã duyệt",
            "reject": "Từ chối",
            "restore": "Thu hồi"
        }.get(action, "Không xác định")

        ghi_chu = {
            "approve": f"Đã trừ {so_ca_nghi} ca phép.",
            "reject": f"Từ chối đơn. {ly_do_tu_choi or ''}",
            "restore": f"Đã hoàn lại {so_ca_nghi} ca phép."
        }.get(action, "")

        cursor.execute("""
            UPDATE DonNghiPhep
            SET TrangThaiDuyet = ?, NguoiDuyet = ?, NgayDuyet = GETDATE(), GhiChu = ?
            WHERE MaDon = ?
        """, (trang_thai_text, nguoi_duyet, ghi_chu, ma_don))

        msg = ""

        # ============================================================
        # 3️⃣ Hành động chính
        # ============================================================
        if action == "approve":
            if trang_thai_hien_tai == "Đã duyệt":
                msg = f"⚠️ Đơn {ma_don} đã được duyệt trước đó."
            else:
                # 🟩 Lịch làm việc → Nghỉ phép (3)
                cursor.execute("""
                    UPDATE llv
                    SET llv.TrangThai = 3
                    FROM LichLamViec llv
                    INNER JOIN DonNghiPhep_CaLam c 
                        ON llv.MaCa = c.MaCa AND llv.NgayLam = c.NgayNghi
                    INNER JOIN DonNghiPhep d ON d.MaDon = c.MaDon AND llv.MaNV = d.MaNV
                    WHERE d.MaDon = ? AND llv.DaXoa = 1
                """, (ma_don,))

                # 🟩 ChamCong → cập nhật hoặc thêm mới (TrangThai = 3, CoDon = 1)
                for ma_ca, ngay in ca_list:
                    cursor.execute("""
                        IF EXISTS (SELECT 1 FROM ChamCong WHERE MaNV=? AND MaCa=? AND NgayChamCong=?)
                            UPDATE ChamCong SET TrangThai=3, CoDon=1
                            WHERE MaNV=? AND MaCa=? AND NgayChamCong=?;
                        ELSE
                            INSERT INTO ChamCong (MaNV, NgayChamCong, MaCa, TrangThai, CoDon, DaXoa)
                            VALUES (?, ?, ?, 3, 1, 1);
                    """, (ma_nv, ma_ca, ngay, ma_nv, ma_ca, ngay, ma_nv, ngay, ma_ca))

                # 🟩 Trừ phép
                cursor.execute("""
                    UPDATE NhanVien
                    SET SoCaPhepConLai = CASE 
                        WHEN SoCaPhepConLai >= ? THEN SoCaPhepConLai - ? ELSE 0 END
                    WHERE MaNV = ?
                """, (so_ca_nghi, so_ca_nghi, ma_nv))
                msg = f"✅ Đã duyệt đơn {ma_don}, trừ {so_ca_nghi} ca phép."

        elif action == "reject":
            msg = f"❌ Đơn {ma_don} bị từ chối. Không trừ phép."

        elif action == "restore":
            if trang_thai_hien_tai != "Đã duyệt":
                msg = f"⚠️ Đơn {ma_don} chưa được duyệt, không thể thu hồi."
            else:
                # 🟦 Hoàn lại phép (tối đa 36)
                cursor.execute("""
                    UPDATE NhanVien
                    SET SoCaPhepConLai = CASE 
                        WHEN SoCaPhepConLai + ? > 36 THEN 36
                        ELSE SoCaPhepConLai + ? END
                    WHERE MaNV = ?
                """, (so_ca_nghi, so_ca_nghi, ma_nv))

                # 🟦 LLV → khôi phục 0 (chưa chấm)
                cursor.execute("""
                    UPDATE llv
                    SET llv.TrangThai = 0
                    FROM LichLamViec llv
                    INNER JOIN DonNghiPhep_CaLam c 
                        ON llv.MaCa = c.MaCa AND llv.NgayLam = c.NgayNghi
                    INNER JOIN DonNghiPhep d ON d.MaDon = c.MaDon AND llv.MaNV = d.MaNV
                    WHERE d.MaDon = ? AND llv.TrangThai = 3 AND llv.DaXoa = 1
                """, (ma_don,))

                # 🟦 ChamCong → reset
                for ma_ca, ngay in ca_list:
                    cursor.execute("""
                        UPDATE ChamCong
                        SET TrangThai = NULL, CoDon = 0
                        WHERE MaNV=? AND MaCa=? AND NgayChamCong=? AND CoDon=1
                    """, (ma_nv, ma_ca, ngay))
                msg = f"♻️ Đã thu hồi đơn {ma_don}, hoàn {so_ca_nghi} ca phép."

        conn.commit()

        # ============================================================
        # 4️⃣ Gửi email + ghi log — FINAL FIXED (Không còn lỗi context)
        # ============================================================
        cursor.execute("SELECT HoTen, Email FROM NhanVien WHERE MaNV=?", (ma_nv,))
        nv = cursor.fetchone()
        if nv:
            ho_ten, email_nv = nv

            def html_mail(color, title, content):
                return f"""
                <div style='font-family:Arial;padding:20px;border:1px solid #eee;border-radius:10px;background:#f9f9fb'>
                    <h2 style='color:{color};text-align:center;margin-top:0'>{title}</h2>
                    <div style='font-size:15px;color:#333;line-height:1.6'>{content}</div>
                    <hr style='border:none;border-top:1px dashed #ccc;margin:16px 0;'>
                    <div style='font-size:12px;color:#888;text-align:center'>
                        Email tự động từ hệ thống FaceID — vui lòng không trả lời
                    </div>
                </div>"""

            if action == "approve":
                subject = f"✅ Đơn nghỉ phép {ma_don} đã được duyệt"
                html_body = html_mail("#2ecc71", "ĐƠN NGHỈ PHÉP ĐÃ DUYỆT", f"""
                    <p>Xin chào <b>{ho_ten}</b>,</p>
                    <p>Đơn nghỉ phép <b>{ma_don}</b> đã được duyệt bởi <b>{nguoi_duyet}</b>.</p>
                    <p>Số ca: <b>{so_ca_nghi}</b> | Thời gian: {tu_ngay:%Y-%m-%d} → {den_ngay:%Y-%m-%d}</p>
                    <p><i>Ngày duyệt: {datetime.now():%d/%m/%Y %H:%M}</i></p>
                """)
                loai = "Duyệt đơn nghỉ phép"

            elif action == "reject":
                subject = f"❌ Đơn nghỉ phép {ma_don} bị từ chối"
                html_body = html_mail("#e74c3c", "ĐƠN NGHỈ PHÉP BỊ TỪ CHỐI", f"""
                    <p>Xin chào <b>{ho_ten}</b>,</p>
                    <p>Đơn nghỉ phép <b>{ma_don}</b> đã bị từ chối bởi <b>{nguoi_duyet}</b>.</p>
                    <p><b>Lý do:</b> {ly_do_tu_choi or "Không có lý do cụ thể."}</p>
                    <p><i>Ngày từ chối: {datetime.now():%d/%m/%Y %H:%M}</i></p>
                """)
                loai = "Từ chối đơn nghỉ phép"

            else:
                subject = f"♻️ Đơn nghỉ phép {ma_don} đã được thu hồi"
                html_body = html_mail("#3498db", "ĐƠN NGHỈ PHÉP ĐÃ THU HỒI", f"""
                    <p>Xin chào <b>{ho_ten}</b>,</p>
                    <p>Đơn nghỉ phép <b>{ma_don}</b> đã được thu hồi bởi <b>{nguoi_duyet}</b>.</p>
                    <p>Hoàn lại <b>{so_ca_nghi}</b> ca phép đã trừ.</p>
                    <p><i>Ngày thu hồi: {datetime.now():%d/%m/%Y %H:%M}</i></p>
                """)
                loai = "Thu hồi đơn nghỉ phép"

            # ✅ Lấy app TRƯỚC KHI tạo thread (quan trọng)
            app = current_app._get_current_object()

            def send_mail_thread(flask_app, subject, email_to, html_body):
                # ✅ Dùng app.app_context() trong thread
                with flask_app.app_context():
                    try:
                        mail = Mail(flask_app)
                        msg = Message(subject=subject, recipients=[email_to], html=html_body)
                        mail.send(msg)
                        print(f"[MAIL] ✅ {subject} → {email_to}")
                    except Exception as err:
                        print(f"[MAIL ERROR] {err}")

            # ✅ Tạo và khởi chạy thread
            Thread(target=send_mail_thread, args=(app, subject, email_nv, html_body)).start()

            # ✅ Ghi log
            cursor.execute("""
                INSERT INTO LichSuEmail (EmailTo, LoaiThongBao, ThoiGian, TrangThai, MaThamChieu)
                VALUES (?, ?, GETDATE(), N'Đã gửi', ?)
            """, (email_nv, loai, ma_don))
            conn.commit()

        return jsonify({"success": True, "message": msg})

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] ❌ Lỗi duyệt đơn nghỉ phép: {e}")
        return jsonify({"success": False, "message": f"❌ Lỗi: {e}"}), 500
    finally:
        conn.close()

=======
>>>>>>> 8958be4bf30293afe01c40a84b84664a9210450c
