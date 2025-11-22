from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from datetime import datetime
from core.db_utils import get_sql_connection
from core.decorators import require_role
from core.log_utils import ghi_lich_su

setting_bp = Blueprint("setting_bp", __name__)

# ============================================================
# ⚙️ TRANG CÀI ĐẶT HỆ THỐNG (Admin + HR)
# ============================================================
@setting_bp.route("/settings", methods=["GET"])
@require_role("admin")
def settings_view():
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # 🧩 Lấy toàn bộ tham số lương
        cursor.execute("SELECT TenThamSo, GiaTri, GhiChu, Nhom FROM ThamSoLuong ORDER BY TenThamSo")
        rows = cursor.fetchall()
        thamso_list = [dict(zip([col[0] for col in cursor.description], row)) for row in rows]

        # 🏷️ Lấy nhóm tham số hệ thống (nếu có)
        settings = {
            "system_name": "FaceID System",
            "company_name": "Công ty TNHH Demo",
            "timezone": "Asia/Ho_Chi_Minh"
        }

        cursor.execute("SELECT TenThamSo, GiaTri FROM ThamSoLuong WHERE Nhom = 'System'")
        system_rows = cursor.fetchall()
        for ten, giatri in system_rows:
            if ten.lower() == "system_name":
                settings["system_name"] = giatri
            elif ten.lower() == "company_name":
                settings["company_name"] = giatri
            elif ten.lower() == "timezone":
                settings["timezone"] = giatri

        # 🧾 Ghi log truy cập
        ghi_lich_su(
            ten_bang="ThamSoLuong",
            ma_ban_ghi=None,
            hanh_dong="Xem trang cài đặt hệ thống",
            gia_tri_moi="Mở trang cài đặt hệ thống",
            nguoi_thuc_hien=session.get("username", "Hệ thống"),
            ip=request.remote_addr,
            device=request.user_agent.string,
            scope="SETTINGS_VIEW"
        )

        # 🟢 Trả về template có cả tham số và settings
        return render_template("setting.html", thamso_list=thamso_list, settings=settings)

    except Exception as e:
        flash(f"Lỗi khi tải tham số hệ thống: {e}", "danger")
        return render_template("setting.html", thamso_list=[], settings={})
    finally:
        conn.close()

# ============================================================
# 💾 CẬP NHẬT GIÁ TRỊ MỘT THAM SỐ LƯƠNG
# ============================================================
@setting_bp.route("/settings/update", methods=["POST"])
@require_role("admin")
def update_setting():
    data = request.get_json() or {}
    name = data.get("name")
    value = data.get("value")

    if not name:
        return jsonify({"success": False, "message": "Thiếu tên tham số!"}), 400

    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")
    ma_tk = session.get("user_id", 1)
    ip = request.remote_addr
    device = request.user_agent.string

    try:
        cursor.execute("SELECT GiaTri FROM ThamSoLuong WHERE TenThamSo = ?", (name,))
        row = cursor.fetchone()
        old_value = row[0] if row else None

        cursor.execute("""
            UPDATE ThamSoLuong
            SET GiaTri = ?, GhiChu = ISNULL(GhiChu, N'')
            WHERE TenThamSo = ?
        """, (value, name))
        conn.commit()

        # 🧾 Ghi vào bảng LichSuHeThong
        cursor.execute("""
            INSERT INTO LichSuHeThong (MaTK, HanhDong, NoiDung, KetQua, IP, ThietBi, ThoiGian, NguoiThucHien, Scope)
            VALUES (?, N'Cập nhật tham số lương', ?, N'Thành công', ?, ?, GETDATE(), ?, ?)
        """, (
            ma_tk,
            f"Cập nhật {name}: {old_value} → {value}",
            ip,
            device[:250],
            username,
            "SETTINGS_UPDATE"
        ))
        conn.commit()

        return jsonify({"success": True, "message": f"✅ Đã cập nhật {name} = {value}"})

    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": f"Lỗi khi cập nhật: {e}"})
    finally:
        conn.close()

# ============================================================
# 💾 LƯU CÀI ĐẶT HỆ THỐNG
# ============================================================
@setting_bp.route("/save_settings", methods=["POST"])
@require_role("admin")
def save_settings():
    conn = get_sql_connection()
    cursor = conn.cursor()

    system_name = request.form.get("system_name")
    company_name = request.form.get("company_name")
    timezone = request.form.get("timezone")

    username = session.get("username", "Hệ thống")
    ma_tk = session.get("user_id", 1)
    ip = request.remote_addr
    device = request.user_agent.string

    try:
        # 🔄 Cập nhật hoặc chèn các tham số nhóm 'System'
        for ten, giatri in [
            ("system_name", system_name),
            ("company_name", company_name),
            ("timezone", timezone),
        ]:
            cursor.execute("""
                IF EXISTS (SELECT 1 FROM ThamSoLuong WHERE TenThamSo = ?)
                    UPDATE ThamSoLuong
                    SET GiaTri = ?, Nhom = 'System', 
                        NguoiCapNhat = ?, NgayCapNhat = GETDATE()
                    WHERE TenThamSo = ?
                ELSE
                    INSERT INTO ThamSoLuong (TenThamSo, GiaTri, Nhom, NguoiCapNhat, NgayCapNhat)
                    VALUES (?, ?, 'System', ?, GETDATE())
            """, (ten, giatri, username, ten, ten, giatri, username))
        conn.commit()

        # 🧾 Ghi log hệ thống
        cursor.execute("""
            INSERT INTO LichSuHeThong (MaTK, HanhDong, NoiDung, KetQua, IP, ThietBi, ThoiGian, NguoiThucHien, Scope)
            VALUES (?, N'Lưu cài đặt hệ thống', ?, N'Thành công', ?, ?, GETDATE(), ?, ?)
        """, (
            ma_tk,
            f"Hệ thống: {system_name} | Công ty: {company_name} | Timezone: {timezone}",
            ip,
            device[:250],
            username,
            "SYSTEM_SETTINGS"
        ))
        conn.commit()

        flash("✅ Đã lưu thông tin hệ thống!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi lưu cài đặt: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("setting_bp.settings_view"))

# ============================================================
# 🎥 LƯU CẤU HÌNH CAMERA
# ============================================================
@setting_bp.route("/save_camera_settings", methods=["POST"])
@require_role("admin")
def save_camera_settings():
    conn = get_sql_connection()
    cursor = conn.cursor()

    camera_ip = request.form.get("camera_ip")
    camera_port = request.form.get("camera_port")

    username = session.get("username", "Hệ thống")
    ma_tk = session.get("user_id", 1)
    ip = request.remote_addr
    device = request.user_agent.string

    try:
        cursor.execute("""
            INSERT INTO LichSuHeThong (MaTK, HanhDong, NoiDung, KetQua, IP, ThietBi, ThoiGian, NguoiThucHien, Scope)
            VALUES (?, N'Lưu cấu hình camera', ?, N'Thành công', ?, ?, GETDATE(), ?, ?)
        """, (
            ma_tk,
            f"IP={camera_ip}, Port={camera_port}",
            ip,
            device[:250],
            username,
            "CAMERA_SETTINGS"
        ))
        conn.commit()

        flash("✅ Đã lưu cấu hình camera!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Lỗi khi lưu cấu hình camera: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("setting_bp.settings_view"))

# ============================================================
# 💾 SAO LƯU DỮ LIỆU HỆ THỐNG
# ============================================================
@setting_bp.route("/backup_data", methods=["GET"])
@require_role("admin")
def backup_data():
    """Thực hiện sao lưu database FaceID"""
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # 📦 Đường dẫn và tên file backup
        backup_dir = "D:\\FaceID_Backup"
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)

        backup_file = f"{backup_dir}\\FaceID_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"

        # 🧩 Câu lệnh backup
        cursor.execute(f"""
            BACKUP DATABASE FaceID
            TO DISK = N'{backup_file}'
            WITH INIT, STATS = 5
        """)
        conn.commit()

        flash(f"✅ Đã sao lưu dữ liệu vào: {backup_file}", "success")

        # 🧾 Ghi log lại
        cursor.execute("""
            INSERT INTO LichSuHeThong (MaTK, HanhDong, NoiDung, KetQua, IP, ThietBi, ThoiGian, NguoiThucHien, Scope)
            VALUES (?, N'Sao lưu dữ liệu', ?, N'Thành công', ?, ?, GETDATE(), ?, ?)
        """, (
            session.get("user_id", 1),
            backup_file,
            request.remote_addr,
            request.user_agent.string[:250],
            session.get("username", "Hệ thống"),
            "DATA_BACKUP"
        ))
        conn.commit()

    except Exception as e:
        flash(f"❌ Lỗi sao lưu dữ liệu: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("setting_bp.settings_view"))

# ============================================================
# ♻️ KHÔI PHỤC DỮ LIỆU HỆ THỐNG
# ============================================================
@setting_bp.route("/restore_data", methods=["GET"])
@require_role("admin")
def restore_data():
    """Khôi phục dữ liệu từ file backup .bak"""
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # 🔁 Tên file khôi phục gần nhất (hoặc chọn file cố định)
        backup_file = "D:\\FaceID_Backup\\FaceID_LATEST.bak"
        db_name = "FaceID"

        # ⚠️ SQL Server không cho khôi phục DB đang sử dụng, nên cần đổi sang master
        cursor.execute(f"""
            USE master;
            ALTER DATABASE {db_name} SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
            RESTORE DATABASE {db_name} FROM DISK = N'{backup_file}' WITH REPLACE;
            ALTER DATABASE {db_name} SET MULTI_USER;
        """)
        conn.commit()

        flash("✅ Đã khôi phục dữ liệu thành công!", "success")

        # 🧾 Ghi log
        cursor.execute("""
            INSERT INTO LichSuHeThong (MaTK, HanhDong, NoiDung, KetQua, IP, ThietBi, ThoiGian, NguoiThucHien, Scope)
            VALUES (?, N'Khôi phục dữ liệu', ?, N'Thành công', ?, ?, GETDATE(), ?, ?)
        """, (
            session.get("user_id", 1),
            backup_file,
            request.remote_addr,
            request.user_agent.string[:250],
            session.get("username", "Hệ thống"),
            "DATA_RESTORE"
        ))
        conn.commit()

    except Exception as e:
        flash(f"❌ Lỗi khôi phục dữ liệu: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("setting_bp.settings_view"))
