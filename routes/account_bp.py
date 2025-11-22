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

def send_mail_background(email, subject, body):
    """Gửi email trong thread an toàn với Flask context."""
    app = current_app._get_current_object()  # Lấy app thật (không proxy)

    def _send():
        with app.app_context():  # 🔒 Tạo context cho thread
            try:
                send_email_notification(email, subject, body)
                print(f"📧 [OK] Đã gửi email nền đến {email}")
            except Exception as e:
                print(f"❌ [THREAD ERROR] Không gửi được email: {e}")

    Thread(target=_send, daemon=True).start()


from flask import current_app, session, flash
from threading import Thread
from core.db_utils import get_sql_connection
from core.email_utils import notify_attendance

def change_account_status(identifier, new_status, action_name):
    """
    ✅ Cập nhật trạng thái tài khoản (khóa / kích hoạt)
    - Có thể truyền vào MaNV hoặc TenDangNhap
    - Gửi email thông báo trong nền (Flask context)
    - Ghi log vào LichSuThayDoi + LichSuEmail
    """
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        print(f"🔍 [DEBUG] Bắt đầu thay đổi trạng thái cho '{identifier}' → {new_status}")

        # 1️⃣ Lấy thông tin tài khoản (tìm theo MaNV hoặc TenDangNhap)
        cursor.execute("""
            SELECT MaTK, MaNV, TenDangNhap, TrangThai
            FROM TaiKhoan
            WHERE MaNV = ? OR TenDangNhap = ?
        """, (identifier, identifier))
        row_tk = cursor.fetchone()

        if not row_tk:
            print("⚠️ Không có tài khoản ứng với nhân viên hoặc tên đăng nhập.")
            flash("❌ Không tìm thấy tài khoản tương ứng!", "danger")
            return False

        ma_tk, ma_nv, username, old_status = row_tk
        print(f"✅ Tìm thấy tài khoản: {username} (MaNV={ma_nv or 'NULL'}) — TrangThai cũ: {old_status}")

        # 2️⃣ Cập nhật trạng thái mới
        cursor.execute("""
            UPDATE TaiKhoan
            SET TrangThai = ?
            WHERE MaTK = ?
        """, (new_status, ma_tk))
        print("✅ Đã cập nhật trạng thái tài khoản.")

        # 3️⃣ Ghi log thay đổi
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien
            )
            VALUES (N'TaiKhoan', ?, ?, N'TrangThai', ?, ?, GETDATE(), ?)
        """, (
            str(ma_nv or username),
            action_name,
            str(old_status),
            str(new_status),
            session.get("user_id", "Hệ thống")
        ))
        print("📝 Đã ghi log LichSuThayDoi.")

        # 4️⃣ Lấy thông tin email nhân viên (nếu có)
        cursor.execute("""
            SELECT NV.Email, NV.HoTen
            FROM NhanVien NV
            WHERE NV.MaNV = ?
        """, (ma_nv,))
        nv_row = cursor.fetchone()

        email = nv_row[0] if nv_row else None
        hoten = nv_row[1] if nv_row else username

        if not email:
            print(f"⚠️ Không có email cho nhân viên {hoten} ({username}).")
        else:
            # 5️⃣ Chuẩn bị nội dung email
            if new_status == 0:
                subject = "🔒 Tài khoản của bạn đã bị khóa"
                body = (
                    f"Kính gửi {hoten},<br><br>"
                    f"Tài khoản của bạn (Tên đăng nhập: <b>{username}</b>) đã bị <b>khóa</b>.<br>"
                    f"Vui lòng liên hệ phòng nhân sự để được hỗ trợ.<br><br>"
                    f"Trân trọng,<br><b>Hệ thống FaceID</b>"
                )
                loai_thong_bao = "Khóa tài khoản"
            else:
                subject = "🔓 Tài khoản của bạn đã được kích hoạt"
                body = (
                    f"Kính gửi {hoten},<br><br>"
                    f"Tài khoản của bạn (Tên đăng nhập: <b>{username}</b>) đã được <b>kích hoạt trở lại</b>.<br>"
                    f"Chúc bạn làm việc hiệu quả!<br><br>"
                    f"Trân trọng,<br><b>Hệ thống FaceID</b>"
                )
                loai_thong_bao = "Mở khóa tài khoản"

            # 6️⃣ Gửi email nền (giữ đúng Flask context)
            app = current_app._get_current_object()

            def background_job():
                with app.app_context():
                    try:
                        send_email_notification(
                            to_email = email,
                            subject=subject,
                            html_body=body,
                            loai=loai_thong_bao,
                            ma_tham_chieu=str(ma_nv or username),
                            ma_tk=ma_tk
                        )
                        print(f"✅ Email đã gửi đến {email} — {subject}")
                    except Exception as e:
                        print(f"❌ [EMAIL ERROR] {e}")

            Thread(target=background_job, daemon=True).start()
            print(f"📤 Đang gửi email nền {loai_thong_bao} đến {email}...")

            # 7️⃣ Ghi log email
            cursor.execute("""
                INSERT INTO LichSuEmail (MaTK, EmailTo, LoaiThongBao, ThoiGian, TrangThai)
                VALUES (?, ?, ?, GETDATE(), N'Đang gửi (nền)')
            """, (ma_tk, email, loai_thong_bao))

        # 8️⃣ Lưu thay đổi
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


# ============================================================
# ✅ VÔ HIỆU HÓA (XÓA MỀM)
# ============================================================
@account_bp.route("/accounts/deactivate/<username>", methods=["POST"])
@require_role("admin")
def deactivate_account(username):
    """Vô hiệu hóa (xóa mềm) tài khoản."""
    if change_account_status(username, 0, "Vô hiệu hóa"):
        flash(f"Đã vô hiệu hóa tài khoản: {username}", "warning")
    else:
        flash(f"Lỗi khi vô hiệu hóa tài khoản: {username}", "danger")
    return redirect(url_for("account_bp.accounts"))

# ============================================================
# ✅ CHUYỂN TRẠNG THÁI (AJAX)
# ============================================================
@account_bp.route("/accounts/toggle_status/<username>", methods=["POST"])
@require_role("admin")
def toggle_account_status(username):
    """Chuyển trạng thái hoạt động / ngừng hoạt động (AJAX)."""
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

# ============================================================
# ✅ XÓA MỀM (CHO NÚT RIÊNG)
# ============================================================
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
    return redirect(request.referrer or url_for("account_bp.deleted_accounts_list"))


# KHÔI PHỤC NHIỀU TÀI KHOẢN

@account_bp.route("/accounts/restore-multiple", methods=["POST"])
@require_role("admin")
def restore_multiple_accounts():
    """Khôi phục nhiều tài khoản đã bị vô hiệu hóa."""
    selected_usernames = request.form.getlist("selected_accounts")
    print("📦 DANH SÁCH GỬI LÊN:", selected_usernames)  # debug tạm thời

    if not selected_usernames:
        flash("⚠️ Chưa chọn tài khoản nào để khôi phục!", "warning")
        return redirect(url_for("account_bp.deleted_accounts_list"))


    count = 0
    for uname in selected_usernames:
        if change_account_status(uname, 1, "Khôi phục nhiều"):
            count += 1

    flash(f"Đã khôi phục {count} tài khoản thành công.", "success")
    return redirect(request.referrer or url_for("account_bp.deleted_accounts_list"))


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
