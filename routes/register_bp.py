from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.security import generate_password_hash
import datetime as dt
import time as tm
from core.add_employee import generate_ma_nv, add_new_employee

# ✅ Import các hàm cần thiết
from core.db_utils import get_connection, get_phongbans
from core.face_utils import encode_and_save
from core.face_utils import async_encode_face
from routes.capture_photo_and_save import capture_photo_and_save
from core.add_employee import generate_ma_nv

from routes.attendance_system import current_employee


# Blueprint
register_bp = Blueprint("register_bp", __name__)

# ===============================
# Route /register
# ===============================
@register_bp.route("/register", methods=["GET", "POST"])
def register():
    phongbans = get_phongbans()

    if request.method == "POST":
        hoten = request.form.get("HoTen", "").strip()
        email = request.form.get("Email", "").strip()
        sdt = request.form.get("SDT", "").strip()
        gioitinh_input = request.form.get("GioiTinh", "").strip().lower()
        ngaysinh = request.form.get("NgaySinh", "").strip()
        diachi = request.form.get("DiaChi", "").strip()
        ma_pb = request.form.get("PhongBan", "").strip()
        chucvu = request.form.get("ChucVu", "").strip()

        if not hoten or not email or not ma_pb:
            flash("⚠️ Vui lòng điền đầy đủ thông tin bắt buộc!", "danger")
            return redirect(url_for("register_bp.register"))

        gioitinh = 1 if gioitinh_input == "nam" else 0 if gioitinh_input == "nữ" else None
        if gioitinh is None:
            flash("⚠️ Giới tính không hợp lệ. Vui lòng nhập 'Nam' hoặc 'Nữ'.", "danger")
            return redirect(url_for("register_bp.register"))

        conn = get_connection()
        cursor = conn.cursor()

        try:
            start_all = tm.time()

            # 1️⃣ Sinh mã NV và thêm nhân viên mới
            ma_nv_moi = generate_ma_nv()

            add_new_employee(cursor, conn, ma_nv_moi, hoten, email, sdt, gioitinh, ngaysinh, diachi, ma_pb, chucvu)
            print(f"✅ Đã thêm nhân viên {ma_nv_moi}")

            # 2️⃣ Tạo tài khoản đăng nhập
            role = "nhanvien"
            role_id = 4
            if "hr" in chucvu.lower():
                role, role_id = "hr", 2
            elif "quản lý" in chucvu.lower() or "trưởng phòng" in chucvu.lower():
                role, role_id = "quanlyphongban", 3

            username = ma_nv_moi
            password_hash = generate_password_hash("123456", method="scrypt")

            cursor.execute("""
                INSERT INTO TaiKhoan (TenDangNhap, MatKhauHash, VaiTro, MaVT, TrangThai, NgayTao, MaNV, DaDangKyKhuonMat)
                VALUES (?, ?, ?, ?, 1, GETDATE(), ?, 0)
            """, (username, password_hash, role, role_id, ma_nv_moi))
            conn.commit()
            print(f"🔑 Đã tạo tài khoản [{role.upper()}] cho {ma_nv_moi}")

            # 3️⃣ Nếu là quản lý → cập nhật phòng ban
            capbac = {"Giám đốc": 1, "Trưởng phòng": 2, "Quản lý": 3}
            if chucvu in capbac:
                cursor.execute("""
                    SELECT nv.MaNV, nv.ChucVu
                    FROM PhongBan pb
                    LEFT JOIN NhanVien nv ON pb.QuanLyPB = nv.MaNV
                    WHERE pb.MaPB = ?
                """, (ma_pb,))
                current_manager = cursor.fetchone()

                current_rank = capbac.get(current_manager[1], 999) if current_manager and current_manager[1] else 999
                new_rank = capbac.get(chucvu, 999)

                if not current_manager or new_rank < current_rank:
                    cursor.execute("""
                        UPDATE PhongBan
                        SET QuanLyPB = ?
                        WHERE MaPB = ?
                    """, (ma_nv_moi, ma_pb))
                    conn.commit()
                    print(f"🏢 Cập nhật {ma_nv_moi} làm quản lý phòng {ma_pb}")

            # 4️⃣ Chụp ảnh và encode khuôn mặt
            image_path = capture_photo_and_save(ma_nv_moi)
            if image_path:
                encode_and_save(ma_nv_moi, image_path, conn)
                flash(f"✅ Đã thêm nhân viên {hoten} ({chucvu}) và tạo tài khoản [{role.upper()}]. Ảnh khuôn mặt đã được lưu.", "success")
            else:
                flash(f"⚠️ Nhân viên {hoten} thêm thành công nhưng chưa có ảnh khuôn mặt.", "warning")

            print(f"🕒 Tổng thời gian xử lý: {tm.time() - start_all:.2f}s")

        except Exception as e:
            conn.rollback()
            import traceback, sys
            traceback.print_exc(file=sys.stdout)
            flash(f"❌ Lỗi khi thêm nhân viên: {e}", "danger")
        finally:
            conn.close()

        return redirect(url_for("register_bp.register"))

    return render_template("register.html", phongbans=phongbans)


# ===============================
# API lấy nhân viên gần nhất
# ===============================


@register_bp.route("/get_current_employee")
def get_current_employee():
    global current_employee
    from flask import current_app
    current_app.logger.info(f"📡 current_employee = {current_employee}")

    if current_employee and current_employee.get("found"):
        return jsonify({
            "found": True,
            "MaNV": current_employee.get("MaNV"),
            "HoTen": current_employee.get("HoTen"),
            "PhongBan": current_employee.get("PhongBan"),
            "NgayChamCong": current_employee.get("NgayChamCong"),
            "GioVao": current_employee.get("GioVao"),
            "GioRa": current_employee.get("GioRa"),
            "CaLam": current_employee.get("CaLam", "-"),
            "TrangThai": current_employee.get("TrangThai")
        })
    return jsonify({"found": False})

