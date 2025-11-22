# ============================================================
# 🕒 CẬP NHẬT VẮNG MẶT / NGHỈ PHÉP (FINAL + GHI LOG LỊCH SỬ)
# ============================================================

from flask import Blueprint, redirect, url_for, flash, current_app, request, session
from datetime import date
from threading import Thread
from core.db_utils import get_sql_connection
from core.decorators import require_role
from core.email_utils import notify_attendance, send_otp_email, send_email_with_attachment, send_email_background, send_email_notification

update_absences_bp = Blueprint("update_absences_bp", __name__)

@update_absences_bp.route("/update_absences", methods=["POST"])
@require_role("admin", "hr")
def update_absences():
    """
    ✅ Cập nhật trạng thái tự động cho CA HIỆN TẠI:
       - Ai chưa chấm → Vắng (0)
       - Ai có đơn phép → Nghỉ phép (3)
       - Ai đã chấm → Giữ nguyên (1 hoặc 2)
    ✅ Ghi log vào LichSuThayDoi
    ✅ Gửi mail thông báo
    """

    from datetime import datetime
    conn = get_sql_connection()
    cursor = conn.cursor()
    today = date.today()
    sent_count = 0
    today_absent = today_leave = 0
    username = session.get("username", "Hệ thống")
    ip_addr = request.remote_addr or "127.0.0.1"

    try:
        # ============================================================
        # 1️⃣ LẤY DANH SÁCH ĐƠN NGHỈ PHÉP HỢP LỆ
        # ============================================================
        cursor.execute("""
            SELECT D.MaNV, C.NgayNghi, C.MaCa
            FROM DonNghiPhep D
            INNER JOIN DonNghiPhep_CaLam C ON D.MaDon = C.MaDon
            WHERE D.TrangThaiDuyet = N'Đã duyệt'
              AND (D.DaXoa = 0 OR D.DaXoa IS NULL)
        """)
        approved_leaves = {
            (r[0], r[1].date() if hasattr(r[1], "date") else r[1], r[2])
            for r in cursor.fetchall()
        }

        # ============================================================
        # 2️⃣ XÁC ĐỊNH CA ĐANG DIỄN RA
        # ============================================================
        cursor.execute("""
            SELECT TOP 1 MaCa, GioBatDau, GioKetThuc
            FROM CaLamViec
            WHERE TrangThai = 1
              AND CONVERT(time, GETDATE()) BETWEEN GioBatDau AND GioKetThuc
            ORDER BY GioBatDau
        """)
        ca = cursor.fetchone()
        if not ca:
            flash("⚠️ Hiện tại không có ca nào đang diễn ra!", "warning")
            return redirect(url_for("attendance_bp.attendance_report"))

        ma_ca, gio_bd, gio_kt = ca
        print(f"🔹 Ca hiện tại: {ma_ca} ({gio_bd}–{gio_kt})")

        # ============================================================
        # 3️⃣ LẤY DANH SÁCH NHÂN VIÊN TRONG CA
        # ============================================================
        cursor.execute("""
            SELECT LLV.MaNV, LLV.NgayLam, LLV.MaLLV, LLV.TrangThai
            FROM LichLamViec LLV
            WHERE LLV.MaCa = ? AND LLV.NgayLam = CAST(GETDATE() AS DATE)
              AND LLV.DaXoa = 1
        """, (ma_ca,))
        employees = cursor.fetchall()

        # 🔹 Người đã chấm công
        cursor.execute("""
            SELECT MaNV
            FROM ChamCong
            WHERE MaCa = ? AND NgayChamCong = CAST(GETDATE() AS DATE)
              AND DaXoa = 1
        """, (ma_ca,))
        checked_in = {r[0] for r in cursor.fetchall()}

        # ============================================================
        # 4️⃣ CẬP NHẬT TRẠNG THÁI + GHI LỊCH SỬ
        # ============================================================
        for ma_nv, ngay_lam, ma_llv, old_status in employees:
            if ma_nv in checked_in:
                continue  # đã chấm, bỏ qua

            ngay_val = ngay_lam.date() if hasattr(ngay_lam, "date") else ngay_lam
            key = (ma_nv, ngay_val, ma_ca)
            is_leave = key in approved_leaves
            new_status = 3 if is_leave else 0  # 3 = Nghỉ phép, 0 = Vắng

            # 🟧 Cập nhật LLV
            cursor.execute("""
                UPDATE LichLamViec
                SET TrangThai = ?
                WHERE MaNV = ? AND MaCa = ? AND NgayLam = ?
                  AND DaXoa = 1
                  AND TrangThai NOT IN (1,2,3,4)
            """, (new_status, ma_nv, ma_ca, ngay_val))

            # 🟨 Cập nhật hoặc thêm ChamCong
            cursor.execute("""
                MERGE ChamCong AS T
                USING (SELECT ? AS MaNV, ? AS NgayChamCong, ? AS MaCa) AS S
                ON T.MaNV = S.MaNV AND T.MaCa = S.MaCa AND T.NgayChamCong = S.NgayChamCong
                WHEN MATCHED THEN
                    UPDATE SET T.TrangThai = ?, T.DaXoa = 1
                WHEN NOT MATCHED THEN
                    INSERT (MaNV, NgayChamCong, MaCa, TrangThai, DaXoa)
                    VALUES (S.MaNV, S.NgayChamCong, S.MaCa, ?, 1);
            """, (ma_nv, ngay_val, ma_ca, new_status, new_status))

            # 🧾 Ghi log vào LichSuThayDoi
            cursor.execute("""
                INSERT INTO LichSuThayDoi
                    (TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                     GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien, IPAddress, Scope)
                VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?, ?, ?)
            """, (
                "LichLamViec",
                ma_llv,
                "Cập nhật trạng thái tự động",
                "TrangThai",
                str(old_status),
                str(new_status),
                username,
                ip_addr,
                "Cập nhật vắng mặt"
            ))

            if is_leave:
                today_leave += 1
            else:
                today_absent += 1

        conn.commit()
        print(f"✅ Đã cập nhật: {today_absent} vắng | {today_leave} nghỉ phép (ca {ma_ca})")

        # ============================================================
        # 5️⃣ GỬI MAIL THÔNG BÁO
        # ============================================================
        cursor.execute("""
            SELECT NV.MaNV, NV.HoTen, NV.Email, PB.TenPB, CLV.TenCa,
                   CLV.GioBatDau, CLV.GioKetThuc, CC.NgayChamCong, CC.TrangThai
            FROM ChamCong CC
            JOIN NhanVien NV ON CC.MaNV = NV.MaNV
            JOIN PhongBan PB ON NV.MaPB = PB.MaPB
            JOIN CaLamViec CLV ON CC.MaCa = CLV.MaCa
            WHERE CC.MaCa = ? AND CONVERT(date, CC.NgayChamCong) = CAST(GETDATE() AS DATE)
              AND CC.TrangThai IN (0,3)
              AND NV.TrangThai = 1
              AND NV.Email IS NOT NULL AND NV.Email <> ''
              AND CC.DaXoa = 1
        """, (ma_ca,))
        records = cursor.fetchall()

        app = current_app._get_current_object()

        def send_email_async(app, ma_nv, hoten, email, ten_pb, ten_ca, gio_bd, gio_kt, ngay, trang_thai):
            with app.app_context():
                try:
                    ngay_str = ngay.strftime("%d/%m/%Y") if hasattr(ngay, "strftime") else str(ngay)
                    if trang_thai == 0:
                        subject = f"📩 Thông báo vắng mặt - Ca {ten_ca} ngày {ngay_str}"
                        body = f"""
                        Kính gửi <b>{hoten}</b>,<br><br>
                        Hệ thống FaceID ghi nhận bạn <b>vắng mặt</b> trong ca <b>{ten_ca}</b> ngày <b>{ngay_str}</b>.<br>
                        Thời gian: {gio_bd} - {gio_kt}<br>
                        Phòng ban: {ten_pb}<br><br>
                        Nếu có lý do chính đáng, vui lòng phản hồi phòng nhân sự.<br><br>
                        Trân trọng,<br><b>Hệ thống FaceID</b>
                        """
                    elif trang_thai == 3:
                        subject = f"✅ Nghỉ phép đã duyệt - Ca {ten_ca} ngày {ngay_str}"
                        body = f"""
                        Kính gửi <b>{hoten}</b>,<br><br>
                        Hệ thống FaceID xác nhận bạn <b>nghỉ phép</b> trong ca <b>{ten_ca}</b> ngày <b>{ngay_str}</b>.<br>
                        Thời gian: {gio_bd} - {gio_kt}<br>
                        Phòng ban: {ten_pb}<br><br>
                        Chúc bạn có thời gian nghỉ ngơi hợp lý.<br><br>
                        Trân trọng,<br><b>Hệ thống FaceID</b>
                        """
                    send_email_notification(email, subject, body)
                    print(f"📧 Gửi mail: {hoten} ({email}) — {('Vắng' if trang_thai==0 else 'Nghỉ phép')}")
                except Exception as e:
                    print(f"❌ Lỗi gửi mail cho {hoten}: {e}")

        for nv in records:
            Thread(target=send_email_async, args=(app, *nv), daemon=True).start()
            sent_count += 1

        flash(f"✅ Cập nhật {today_absent} vắng, {today_leave} nghỉ phép cho ca {ma_ca}. Đã gửi {sent_count} email và ghi log.", "success")
        return redirect(url_for("attendance_bp.attendance_report"))

    except Exception as e:
        conn.rollback()
        print(f"❌ Lỗi cập nhật vắng: {e}")
        flash(f"❌ Lỗi cập nhật vắng: {e}", "danger")
        return redirect(url_for("attendance_bp.attendance_report"))

    finally:
        conn.close()

@update_absences_bp.route("/sync_leaves", methods=["POST"])
@require_role("admin", "hr")
def sync_leaves():
    """
    ✅ ĐỒNG BỘ NGHỈ PHÉP — FINAL v7 (Kết hợp Trigger + Flask Sync)
    ------------------------------------------------------------
    ✔ Kiểm tra & kích hoạt trigger SQL nếu bị tắt
    ✔ Đồng bộ ChamCong + LichLamViec (TrangThai=3, CoDon=1)
    ✔ Gửi email xác nhận nghỉ phép
    ✔ Ghi log vào LichSuEmail (MaTK thực tế)
    ------------------------------------------------------------
    """
    from threading import Thread
    from flask import current_app
    from datetime import date

    conn = get_sql_connection()
    cursor = conn.cursor()
    today = date.today()
    sent_count = 0
    username = session.get("username", "Hệ thống")
    ma_tk = None

    # ============================================================
    # 🔍 0️⃣ LẤY MÃ TÀI KHOẢN NGƯỜI THỰC HIỆN
    # ============================================================
    cursor.execute("SELECT MaTK FROM TaiKhoan WHERE TenDangNhap = ?", (username,))
    row = cursor.fetchone()
    if row:
        ma_tk = row[0]
        print(f"[INFO] Người duyệt phép: {username} (MaTK={ma_tk})")
    else:
        print(f"[WARN] Không tìm thấy MaTK cho '{username}' → MaTK=NULL.")

    # ============================================================
    # ⚙️ 1️⃣ KIỂM TRA TRIGGER ĐỒNG BỘ NGHỈ PHÉP
    # ============================================================
    try:
        cursor.execute("""
            SELECT is_disabled FROM sys.triggers WHERE name = 'trg_AutoUpdate_OnLeaveApproved'
        """)
        trig = cursor.fetchone()
        if trig and trig[0] == 1:
            print("⚠️ Trigger trg_AutoUpdate_OnLeaveApproved đang bị tắt → sẽ bật lại.")
            cursor.execute("ENABLE TRIGGER trg_AutoUpdate_OnLeaveApproved ON DonNghiPhep;")
            conn.commit()
        else:
            print("✅ Trigger trg_AutoUpdate_OnLeaveApproved đang hoạt động bình thường.")
    except Exception as e:
        print(f"❌ Không thể kiểm tra trigger: {e}")

    try:
        # ============================================================
        # 2️⃣ XÁC ĐỊNH CA HIỆN TẠI
        # ============================================================
        cursor.execute("""
            SELECT TOP 1 MaCa, TenCa, GioBatDau, GioKetThuc
            FROM CaLamViec
            WHERE TrangThai = 1
              AND CONVERT(time, GETDATE()) BETWEEN GioBatDau AND GioKetThuc
            ORDER BY GioBatDau
        """)
        ca = cursor.fetchone()
        if not ca:
            flash("⚠️ Hiện tại không có ca nào đang diễn ra!", "warning")
            return redirect(url_for("attendance_bp.attendance_report"))

        ma_ca, ten_ca, gio_bd, gio_kt = ca
        print(f"🔹 ĐỒNG BỘ NGHỈ PHÉP — Ca hiện tại: {ten_ca} ({gio_bd}-{gio_kt})")

        # ============================================================
        # 3️⃣ LẤY DANH SÁCH NGHỈ PHÉP TRONG CA
        # ============================================================
        cursor.execute("""
            SELECT D.MaNV, C.NgayNghi, C.MaCa
            FROM DonNghiPhep D
            INNER JOIN DonNghiPhep_CaLam C ON D.MaDon = C.MaDon
            WHERE D.TrangThaiDuyet = N'Đã duyệt'
              AND C.MaCa = ?
              AND CONVERT(date, C.NgayNghi) = CAST(GETDATE() AS DATE)
              AND (D.DaXoa = 0 OR D.DaXoa IS NULL)
        """, (ma_ca,))
        leaves = cursor.fetchall()
        if not leaves:
            flash(f"✅ Không có nhân viên nghỉ phép trong ca {ten_ca} hôm nay.", "info")
            return redirect(url_for("attendance_bp.attendance_report"))

        count = 0

        # ============================================================
        # 4️⃣ CẬP NHẬT CHẤM CÔNG + LỊCH LÀM VIỆC
        # ============================================================
        for ma_nv, ngay, ma_ca in leaves:
            cursor.execute("""
                MERGE ChamCong AS T
                USING (SELECT ? AS MaNV, CONVERT(date, ?) AS NgayChamCong, ? AS MaCa) AS S
                ON T.MaNV = S.MaNV AND T.MaCa = S.MaCa AND CONVERT(date, T.NgayChamCong) = S.NgayChamCong
                WHEN MATCHED THEN
                    UPDATE SET TrangThai = 3, CoDon = 1, DaXoa = 1
                WHEN NOT MATCHED THEN
                    INSERT (MaNV, NgayChamCong, MaCa, TrangThai, CoDon, DaXoa)
                    VALUES (S.MaNV, S.NgayChamCong, S.MaCa, 3, 1, 1);
            """, (ma_nv, ngay, ma_ca))

            cursor.execute("""
                UPDATE LichLamViec
                SET TrangThai = 3
                WHERE MaNV = ? AND MaCa = ?
                  AND CONVERT(date, NgayLam) = CONVERT(date, ?)
                  AND (DaXoa = 1 OR DaXoa IS NULL);
            """, (ma_nv, ma_ca, ngay))
            count += 1

        conn.commit()
        print(f"✅ Đồng bộ thành công {count} ca nghỉ phép ({ten_ca}).")

        # ============================================================
        # 5️⃣ GỬI EMAIL XÁC NHẬN NGHỈ PHÉP
        # ============================================================
        cursor.execute("""
            SELECT NV.HoTen, NV.Email, PB.TenPB, CLV.TenCa,
                   CONVERT(VARCHAR(5), CLV.GioBatDau, 108),
                   CONVERT(VARCHAR(5), CLV.GioKetThuc, 108),
                   C.NgayNghi, NV.MaNV
            FROM DonNghiPhep D
            INNER JOIN DonNghiPhep_CaLam C ON D.MaDon = C.MaDon
            JOIN NhanVien NV ON NV.MaNV = D.MaNV
            JOIN PhongBan PB ON PB.MaPB = NV.MaPB
            JOIN CaLamViec CLV ON CLV.MaCa = C.MaCa
            WHERE D.TrangThaiDuyet = N'Đã duyệt'
              AND C.MaCa = ?
              AND CONVERT(date, C.NgayNghi) = CAST(GETDATE() AS DATE)
              AND NV.Email IS NOT NULL AND NV.Email <> ''
              AND NV.TrangThai = 1;
        """, (ma_ca,))
        records = cursor.fetchall()

        app = current_app._get_current_object()

        def send_leave_mail(app, hoten, email, ten_pb, ten_ca, gio_bd, gio_kt, ngay, ma_nv):
            """Hàm gửi mail riêng từng nhân viên nghỉ phép"""
            with app.app_context():
                try:
                    ngay_str = ngay.strftime("%d/%m/%Y") if hasattr(ngay, "strftime") else str(ngay)
                    subject = f"✅ Nghỉ phép đã duyệt - {ten_ca} ngày {ngay_str}"
                    body = f"""
                    Kính gửi <b>{hoten}</b>,<br><br>
                    Hệ thống FaceID xác nhận bạn <b>nghỉ phép</b> trong ca <b>{ten_ca}</b> ngày <b>{ngay_str}</b>.<br>
                    Thời gian: {gio_bd} - {gio_kt}<br>
                    Phòng ban: {ten_pb}<br><br>
                    Chúc bạn có thời gian nghỉ ngơi hợp lý.<br><br>
                    Trân trọng,<br><b>Hệ thống FaceID</b>
                    """

                    from core.email_utils import send_email_notification
                    send_email_notification(email, subject, body)

                    # 🧾 Ghi log email
                    conn2 = get_sql_connection()
                    cur2 = conn2.cursor()
                    cur2.execute("""
                        INSERT INTO LichSuEmail (EmailTo, LoaiThongBao, ThoiGian, TrangThai, MaTK, MaThamChieu)
                        VALUES (?, N'LEAVE_SYNC', GETDATE(), N'Đã gửi', ?, ?)
                    """, (email, ma_tk, ma_nv))
                    conn2.commit()
                    cur2.close()
                    conn2.close()

                    print(f"📧 Gửi mail nghỉ phép: {hoten} ({email}) — Ca {ten_ca}")
                except Exception as e:
                    print(f"❌ Lỗi gửi mail cho {hoten}: {e}")

        # Gửi mail song song (thread)
        for r in records:
            Thread(target=send_leave_mail, args=(app, *r), daemon=True).start()
            sent_count += 1

        flash(f"✅ Đồng bộ {count} ca nghỉ phép ({ten_ca}) và gửi {sent_count} email xác nhận!", "success")

    except Exception as e:
        conn.rollback()
        print(f"❌ Lỗi đồng bộ nghỉ phép: {e}")
        flash(f"❌ Lỗi đồng bộ nghỉ phép: {e}", "danger")

    finally:
        conn.close()

    return redirect(url_for("attendance_bp.attendance_report"))

@update_absences_bp.route("/sync_all_leaves_today", methods=["POST"])
@require_role("admin", "hr")
def sync_all_leaves_today():
    """
    ✅ ĐỒNG BỘ TẤT CẢ NGHỈ PHÉP TRONG NGÀY — FINAL v3
    ------------------------------------------------------------
    ✔ Duyệt qua toàn bộ ca làm việc trong ngày hiện tại
    ✔ Cập nhật ChamCong + LichLamViec (TrangThai=3, CoDon=1)
    ✔ Kiểm tra & bật lại trigger trg_AutoUpdate_OnLeaveApproved nếu tắt
    ✔ Gửi email xác nhận nghỉ phép + ghi log LichSuEmail
    ------------------------------------------------------------
    """
    from threading import Thread
    from flask import current_app
    from datetime import date

    conn = get_sql_connection()
    cursor = conn.cursor()
    today = date.today()
    sent_count = 0
    username = session.get("username", "Hệ thống")
    ma_tk = None

    # ============================================================
    # 🧩 0️⃣ LẤY MÃ TÀI KHOẢN NGƯỜI THỰC HIỆN
    # ============================================================
    cursor.execute("SELECT MaTK FROM TaiKhoan WHERE TenDangNhap = ?", (username,))
    row = cursor.fetchone()
    if row:
        ma_tk = row[0]
        print(f"[INFO] Người duyệt phép: {username} (MaTK={ma_tk})")
    else:
        print(f"[WARN] Không tìm thấy MaTK cho '{username}' → MaTK=NULL.")

    # ============================================================
    # ⚙️ 1️⃣ KIỂM TRA TRIGGER
    # ============================================================
    try:
        cursor.execute("""
            SELECT is_disabled FROM sys.triggers WHERE name = 'trg_AutoUpdate_OnLeaveApproved'
        """)
        trig = cursor.fetchone()
        if trig and trig[0] == 1:
            print("⚠️ Trigger trg_AutoUpdate_OnLeaveApproved đang bị tắt → bật lại.")
            cursor.execute("ENABLE TRIGGER trg_AutoUpdate_OnLeaveApproved ON DonNghiPhep;")
            conn.commit()
        else:
            print("✅ Trigger trg_AutoUpdate_OnLeaveApproved đang hoạt động.")
    except Exception as e:
        print(f"❌ Lỗi kiểm tra trigger: {e}")

    try:
        # ============================================================
        # 2️⃣ LẤY TOÀN BỘ NGHỈ PHÉP TRONG NGÀY
        # ============================================================
        cursor.execute("""
            SELECT D.MaNV, NV.HoTen, NV.Email, PB.TenPB, CLV.TenCa,
                   CONVERT(VARCHAR(5), CLV.GioBatDau, 108) AS GioBatDau,
                   CONVERT(VARCHAR(5), CLV.GioKetThuc, 108) AS GioKetThuc,
                   C.NgayNghi, C.MaCa
            FROM DonNghiPhep D
            INNER JOIN DonNghiPhep_CaLam C ON D.MaDon = C.MaDon
            JOIN NhanVien NV ON NV.MaNV = D.MaNV
            JOIN PhongBan PB ON PB.MaPB = NV.MaPB
            JOIN CaLamViec CLV ON CLV.MaCa = C.MaCa
            WHERE D.TrangThaiDuyet = N'Đã duyệt'
              AND CONVERT(date, C.NgayNghi) = CAST(GETDATE() AS DATE)
              AND NV.TrangThai = 1
              AND (D.DaXoa = 0 OR D.DaXoa IS NULL)
        """)
        rows = cursor.fetchall()
        if not rows:
            flash("✅ Không có nhân viên nghỉ phép trong ngày hôm nay.", "info")
            return redirect(url_for("attendance_bp.attendance_report"))

        total = len(rows)
        updated = 0

        # ============================================================
        # 3️⃣ CẬP NHẬT CHẤM CÔNG + LỊCH LÀM VIỆC
        # ============================================================
        for ma_nv, hoten, email, ten_pb, ten_ca, gio_bd, gio_kt, ngay, ma_ca in rows:
            cursor.execute("""
                MERGE ChamCong AS T
                USING (SELECT ? AS MaNV, CONVERT(date, ?) AS NgayChamCong, ? AS MaCa) AS S
                ON T.MaNV = S.MaNV AND T.MaCa = S.MaCa AND CONVERT(date, T.NgayChamCong) = S.NgayChamCong
                WHEN MATCHED THEN
                    UPDATE SET TrangThai = 3, CoDon = 1, DaXoa = 1
                WHEN NOT MATCHED THEN
                    INSERT (MaNV, NgayChamCong, MaCa, TrangThai, CoDon, DaXoa)
                    VALUES (S.MaNV, S.NgayChamCong, S.MaCa, 3, 1, 1);
            """, (ma_nv, ngay, ma_ca))

            cursor.execute("""
                UPDATE LichLamViec
                SET TrangThai = 3
                WHERE MaNV = ? AND MaCa = ?
                  AND CONVERT(date, NgayLam) = CONVERT(date, ?)
                  AND (DaXoa = 1 OR DaXoa IS NULL);
            """, (ma_nv, ma_ca, ngay))
            updated += 1

        conn.commit()
        print(f"✅ Đồng bộ thành công {updated}/{total} ca nghỉ phép hôm nay.")

        # ============================================================
        # 4️⃣ GỬI EMAIL XÁC NHẬN NGHỈ PHÉP
        # ============================================================
        app = current_app._get_current_object()

        def send_leave_mail(app, hoten, email, ten_pb, ten_ca, gio_bd, gio_kt, ngay, ma_nv):
            with app.app_context():
                try:
                    ngay_str = ngay.strftime("%d/%m/%Y") if hasattr(ngay, "strftime") else str(ngay)
                    subject = f"✅ Nghỉ phép đã duyệt - {ten_ca} ngày {ngay_str}"
                    body = f"""
                    Kính gửi <b>{hoten}</b>,<br><br>
                    Hệ thống FaceID xác nhận bạn <b>nghỉ phép</b> trong ca <b>{ten_ca}</b> ngày <b>{ngay_str}</b>.<br>
                    Thời gian: {gio_bd} - {gio_kt}<br>
                    Phòng ban: {ten_pb}<br><br>
                    Chúc bạn có thời gian nghỉ ngơi hợp lý.<br><br>
                    Trân trọng,<br><b>Hệ thống FaceID</b>
                    """
                    from core.email_utils import send_email_notification
                    send_email_notification(email, subject, body)

                    conn2 = get_sql_connection()
                    cur2 = conn2.cursor()
                    cur2.execute("""
                        INSERT INTO LichSuEmail (EmailTo, LoaiThongBao, ThoiGian, TrangThai, MaTK, MaThamChieu)
                        VALUES (?, N'LEAVE_SYNC_ALL', GETDATE(), N'Đã gửi', ?, ?)
                    """, (email, ma_tk, ma_nv))
                    conn2.commit()
                    cur2.close()
                    conn2.close()

                    print(f"📧 Gửi mail nghỉ phép: {hoten} ({email}) — Ca {ten_ca}")
                except Exception as e:
                    print(f"❌ Lỗi gửi mail cho {hoten}: {e}")

        # Gửi mail song song
        for r in rows:
            Thread(target=send_leave_mail, args=(app, *r), daemon=True).start()
            sent_count += 1

        flash(f"✅ Đồng bộ toàn bộ {updated} ca nghỉ phép trong ngày và gửi {sent_count} email xác nhận!", "success")

    except Exception as e:
        conn.rollback()
        print(f"❌ Lỗi đồng bộ tất cả nghỉ phép: {e}")
        flash(f"❌ Lỗi đồng bộ tất cả nghỉ phép: {e}", "danger")

    finally:
        conn.close()

    return redirect(url_for("attendance_bp.attendance_report"))

