from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from core.db_utils import get_sql_connection
from core.decorators import require_role
import hashlib
from flask import jsonify
from core.email_utils import send_email_notification
from threading import Thread

account_bp = Blueprint("account_bp", __name__)

# DANH SÁCH TÀI KHOẢN

@account_bp.route("/accounts")
@require_role("admin")
def accounts():
    conn = get_sql_connection()
    cursor = conn.cursor()

    # --- Thống kê tổng quan ---
    cursor.execute("SELECT COUNT(*) FROM TaiKhoan WHERE TrangThai = 1")
    total_accounts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM TaiKhoan WHERE TrangThai = 1")
    active_accounts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM TaiKhoan WHERE TrangThai = 0")
    inactive_accounts = cursor.fetchone()[0]

    # --- Đếm loại tài khoản ---
    cursor.execute("""
        SELECT COUNT(*) 
        FROM TaiKhoan
        WHERE TrangThai = 1
        AND LOWER(VaiTro) IN (N'admin', N'quản trị viên', N'administrator')
    """)
    admin_accounts = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) 
        FROM TaiKhoan
        WHERE TrangThai = 1
        AND LOWER(VaiTro) IN (N'user', N'nhanvien', N'nhân viên', N'người dùng')
    """)
    user_accounts = cursor.fetchone()[0]

    # --- Danh sách tài khoản ---
    cursor.execute("""
        SELECT 
            t.MaTK,
            t.TenDangNhap,
            ISNULL(n.HoTen, N'—') AS HoTen,
            ISNULL(n.Email, N'—') AS Email,
            CASE 
                WHEN LOWER(t.VaiTro) IN (N'admin', N'quản trị viên', N'administrator') THEN N'Quản trị viên'
                WHEN LOWER(t.VaiTro) IN (N'user', N'nhanvien', N'nhân viên', N'người dùng') THEN N'Nhân viên'
                ELSE ISNULL(t.VaiTro, N'Không xác định')
            END AS VaiTro,
            CASE 
                WHEN t.TrangThai = 1 THEN N'Đang hoạt động'
                ELSE N'Ngừng hoạt động'
            END AS TrangThai,
            t.TrangThai AS TrangThaiCode,
            CONVERT(VARCHAR(10), t.NgayTao, 103) AS NgayTao
        FROM TaiKhoan t
        LEFT JOIN NhanVien n ON t.MaNV = n.MaNV
        WHERE t.TrangThai = 1
        ORDER BY t.NgayTao DESC
    """)
    accounts = cursor.fetchall()

    conn.close()

    return render_template(
        "accounts.html",
        accounts=accounts,
        total_accounts=total_accounts,
        active_accounts=active_accounts,
        inactive_accounts=inactive_accounts,
        admin_accounts=admin_accounts,
        user_accounts=user_accounts
    )

# THÊM TÀI KHOẢN

@account_bp.route("/accounts/add", methods=["GET", "POST"])
@require_role("admin")
def add_account():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()

        if not username or not password or not role:
            flash("Vui lòng nhập đầy đủ thông tin!", "danger")
            return redirect(url_for("account_bp.add_account"))

        hashed_password = hashlib.sha256(password.encode("utf-8")).hexdigest()

        conn = get_sql_connection()
        cursor = conn.cursor()

        try:
            # --- Kiểm tra trùng tên đăng nhập ---
            cursor.execute("SELECT COUNT(*) FROM TaiKhoan WHERE TenDangNhap = ?", (username,))
            if cursor.fetchone()[0] > 0:
                flash("Tên đăng nhập đã tồn tại!", "warning")
                conn.close()
                return redirect(url_for("account_bp.add_account"))

            # --- Thêm tài khoản ---
            cursor.execute("""
                INSERT INTO TaiKhoan (TenDangNhap, MatKhauHash, VaiTro, TrangThai, NgayTao)
                VALUES (?, ?, ?, 1, GETDATE())
            """, (username, hashed_password, role))

            # --- Ghi log thay đổi ---
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES ('TaiKhoan', ?, N'Thêm mới', N'Toàn bộ', NULL, ?, GETDATE(), ?)
            """, (username, username, session.get("user_id", "Hệ thống")))

            conn.commit()
            flash("Thêm tài khoản thành công!", "success")

        except Exception as e:
            conn.rollback()
            flash(f"Lỗi khi thêm tài khoản: {e}", "danger")
        finally:
            conn.close()

        return redirect(url_for("account_bp.accounts"))

    return render_template("add_account.html")

# SỬA TÀI KHOẢN

@account_bp.route("/accounts/edit/<username>", methods=["GET", "POST"])
@require_role("admin")
def edit_account(username):
    conn = get_sql_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "").strip()

        if not role:
            flash("Vai trò không được để trống!", "warning")
            return redirect(url_for("account_bp.edit_account", username=username))

        try:
            if password:
                hashed_password = hashlib.sha256(password.encode("utf-8")).hexdigest()
                cursor.execute("""
                    UPDATE TaiKhoan
                    SET MatKhauHash = ?, VaiTro = ?
                    WHERE TenDangNhap = ?
                """, (hashed_password, role, username))
            else:
                cursor.execute("""
                    UPDATE TaiKhoan
                    SET VaiTro = ?
                    WHERE TenDangNhap = ?
                """, (role, username))

            # Ghi log
            cursor.execute("""
                INSERT INTO LichSuThayDoi (
                    TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                    GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
                )
                VALUES ('TaiKhoan', ?, N'Cập nhật', N'VaiTro / MatKhau', NULL, ?, GETDATE(), ?)
            """, (username, role, session.get("user_id", "Hệ thống")))

            conn.commit()
            flash("Cập nhật tài khoản thành công!", "success")

        except Exception as e:
            conn.rollback()
            flash(f"Lỗi khi cập nhật tài khoản: {e}", "danger")
        finally:
            conn.close()

        return redirect(url_for("account_bp.accounts"))

    # --- GET: Lấy thông tin tài khoản ---
    cursor.execute("SELECT TenDangNhap, VaiTro FROM TaiKhoan WHERE TenDangNhap = ?", (username,))
    account = cursor.fetchone()
    conn.close()

    if not account:
        flash("Không tìm thấy tài khoản.", "danger")
        return redirect(url_for("account_bp.accounts"))

    return render_template("edit_account.html", account=account)

# HÀM CHUNG – CẬP NHẬT TRẠNG THÁI TÀI KHOẢN
def send_mail_background(email, subject, body):
    """Hàm gửi email trong thread nền (không làm chậm request chính)."""
    try:
        send_email_notification(email, subject, body)
    except Exception as e:
        print(f"❌ [THREAD] Lỗi gửi email nền: {e}")


def change_account_status(ma_nv, new_status, action_name):
    """
    Cập nhật trạng thái tài khoản (khóa / kích hoạt),
    gửi email thông báo cho nhân viên (nền),
    và ghi log vào LichSuThayDoi + LichSuEmail.
    """
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        print(f"🔍 [DEBUG] Bắt đầu thay đổi trạng thái cho nhân viên {ma_nv} → {new_status}")

        # 1️⃣ Lấy trạng thái cũ
        cursor.execute("SELECT TrangThai FROM TaiKhoan WHERE MaNV = ?", (ma_nv,))
        old_row = cursor.fetchone()
        old_status = old_row[0] if old_row else None

        if old_status is None:
            flash("❌ Không tìm thấy tài khoản tương ứng với nhân viên này!", "danger")
            print("⚠️ Không có tài khoản ứng với nhân viên.")
            return False

        # 2️⃣ Cập nhật trạng thái mới
        cursor.execute("""
            UPDATE TaiKhoan
            SET TrangThai = ?
            WHERE MaNV = ?
        """, (new_status, ma_nv))
        print("✅ Đã cập nhật trạng thái tài khoản.")

        # 3️⃣ Ghi log thay đổi
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (
                N'TaiKhoan', ?, ?, N'TrangThai',
                ?, ?, GETDATE(), ?
            )
        """, (
            ma_nv,
            action_name,
            str(old_status),
            str(new_status),
            session.get("user_id", "Hệ thống")
        ))
        print("📝 Đã ghi log LichSuThayDoi.")

        # 4️⃣ Lấy thông tin nhân viên
        cursor.execute("""
            SELECT TK.MaTK, NV.Email, NV.HoTen
            FROM TaiKhoan TK
            JOIN NhanVien NV ON TK.MaNV = NV.MaNV
            WHERE NV.MaNV = ?
        """, (ma_nv,))
        row = cursor.fetchone()

        if not row:
            print(f"⚠️ Không tìm thấy nhân viên có mã {ma_nv} để gửi email.")
        else:
            ma_tk, email, hoten = row
            print(f"📧 Chuẩn bị gửi email cho {hoten} ({email})")

            # 5️⃣ Chuẩn bị nội dung email
            if new_status == 0:
                subject = "🔒 Tài khoản của bạn đã bị khóa"
                body = (
                    f"Kính gửi {hoten},\n\n"
                    f"Tài khoản của bạn (Mã NV: {ma_nv}) đã bị khóa bởi quản trị viên.\n"
                    f"Vui lòng liên hệ phòng nhân sự để được hỗ trợ.\n\n"
                    f"Trân trọng,\nHệ thống FaceID"
                )
                loai_thong_bao = "Khóa tài khoản"
            else:
                subject = "🔓 Tài khoản của bạn đã được kích hoạt"
                body = (
                    f"Kính gửi {hoten},\n\n"
                    f"Tài khoản của bạn (Mã NV: {ma_nv}) đã được kích hoạt trở lại.\n"
                    f"Chúc bạn làm việc hiệu quả!\n\n"
                    f"Trân trọng,\nHệ thống FaceID"
                )
                loai_thong_bao = "Mở khóa tài khoản"

            # 6️⃣ Gửi email nền (Thread) + ghi log LichSuEmail
            try:
                Thread(target=send_mail_background, args=(email, subject, body), daemon=True).start()
                print(f"📤 Đang gửi email nền {loai_thong_bao} đến {email}...")

                cursor.execute("""
                    INSERT INTO LichSuEmail (MaTK, EmailTo, LoaiThongBao, ThoiGian, TrangThai)
                    VALUES (?, ?, ?, GETDATE(), N'Đang gửi (nền)')
                """, (ma_tk, email, loai_thong_bao))
            except Exception as e:
                print(f"❌ Lỗi khởi tạo thread gửi email: {e}")
                cursor.execute("""
                    INSERT INTO LichSuEmail (MaTK, EmailTo, LoaiThongBao, ThoiGian, TrangThai)
                    VALUES (?, ?, ?, GETDATE(), N'Lỗi khởi tạo thread')
                """, (ma_tk, email, loai_thong_bao))

        # 7️⃣ Lưu tất cả thay đổi
        conn.commit()
        print("💾 COMMIT HOÀN TẤT.")
        flash("✅ Cập nhật trạng thái tài khoản thành công!", "success")
        return True

    except Exception as e:
        conn.rollback()
        print(f"❌ ROLLBACK do lỗi: {e}")
        flash(f"Lỗi khi thay đổi trạng thái tài khoản: {e}", "danger")
        return False

    finally:
        conn.close()
        print("🔚 Đã đóng kết nối SQL.")
        
#VÔ HIỆU HÓA (XÓA MỀM)

@account_bp.route("/accounts/deactivate/<username>", methods=["POST"])
@require_role("admin")
def deactivate_account(username):
    if change_account_status(username, 0, "Vô hiệu hóa"):
        flash(f"Đã vô hiệu hóa tài khoản: {username}", "warning")
    return redirect(url_for("account_bp.accounts"))

# CHUYỂN TRẠNG THÁI (AJAX)

@account_bp.route("/accounts/toggle_status/<username>", methods=["POST"])
@require_role("admin")
def toggle_account_status(username):
    conn = get_sql_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT TrangThai FROM TaiKhoan WHERE TenDangNhap = ?", (username,))
    result = cursor.fetchone()
    conn.close()

    if not result:
        return jsonify({"success": False, "message": "Không tìm thấy tài khoản."})

    new_status = 0 if result[0] == 1 else 1
    change_account_status(username, new_status, "Chuyển trạng thái")

    return jsonify({
        "success": True,
        "username": username,
        "new_status": new_status,
        "status_text": "Đang hoạt động" if new_status == 1 else "Ngừng hoạt động"
    })

#XÓA MỀM (CHO NÚT RIÊNG)

@account_bp.route("/accounts/delete/<username>", methods=["POST"])
@require_role("admin")
def delete_account(username):
    """Vô hiệu hóa (xóa mềm) một tài khoản."""
    if change_account_status(username, 0, "Xóa mềm"):
        flash(f"Đã vô hiệu hóa tài khoản {username}.", "warning")
    else:
        flash(f"Lỗi khi vô hiệu hóa tài khoản {username}.", "danger")
    return redirect(url_for("account_bp.accounts"))

# KHÔI PHỤC MỘT TÀI KHOẢN

@account_bp.route("/accounts/activate/<username>", methods=["POST"])
@require_role("admin")
def activate_account(username):
    """Khôi phục (mở lại) một tài khoản."""
    if change_account_status(username, 1, "Khôi phục"):
        flash(f"Đã khôi phục tài khoản {username} thành công!", "success")
    else:
        flash("Lỗi khi khôi phục tài khoản!", "danger")
    return redirect(request.referrer or url_for("deleted_records", tab="accounts"))

# KHÔI PHỤC NHIỀU TÀI KHOẢN

@account_bp.route("/accounts/restore-multiple", methods=["POST"])
@require_role("admin")
def restore_multiple_accounts():
    """Khôi phục nhiều tài khoản đã bị vô hiệu hóa."""
    selected_usernames = request.form.getlist("selected_accounts")
    print("📦 DANH SÁCH GỬI LÊN:", selected_usernames)  # debug tạm thời

    if not selected_usernames:
        flash("⚠️ Chưa chọn tài khoản nào để khôi phục!", "warning")
        return redirect(url_for("deleted_records", tab="accounts"))

    count = 0
    for uname in selected_usernames:
        if change_account_status(uname, 1, "Khôi phục nhiều"):
            count += 1

    flash(f"ã khôi phục {count} tài khoản thành công.", "success")
    return redirect(url_for("deleted_records", tab="accounts"))

# DANH SÁCH TÀI KHOẢN ĐÃ VÔ HIỆU HÓA

@account_bp.route("/accounts/deleted")
@require_role("admin")
def deleted_accounts_list():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                TK.TenDangNhap,
                ISNULL(NV.HoTen, N'—') AS HoTen,
                ISNULL(NV.Email, N'—') AS Email,
                TK.VaiTro,
                TK.NgayTao
            FROM TaiKhoan TK
            LEFT JOIN NhanVien NV ON TK.MaNV = NV.MaNV
            WHERE TK.TrangThai = 0
            ORDER BY TK.NgayTao DESC

        """)
        deleted_accounts = cursor.fetchall()

    except Exception as e:
        flash(f"Lỗi khi tải danh sách tài khoản đã vô hiệu hóa: {e}", "danger")
        deleted_accounts = []

    finally:
        conn.close()

    return render_template(
        "deleted_records.html",
        active_tab="accounts",
        deleted_accounts=deleted_accounts
    )
