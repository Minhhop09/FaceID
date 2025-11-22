from flask import Blueprint, render_template, jsonify, session, request, redirect, url_for, flash
from datetime import datetime, date
from core.db_utils import get_sql_connection
from core.salary_utils import tinh_luong_nv, get_tham_so_luong, next_ma_ct_luong
from core.decorators import require_role
import uuid
from decimal import Decimal
from core.payment_utils import calc_fee, normalize_account, fake_gateway_charge, generate_txid
from core.email_utils import notify_attendance, send_email_with_attachment
from core.log_utils import ghi_lich_su, log_change, log_payment
import csv
from io import BytesIO, StringIO
import os
from flask import send_file, current_app
import core.payment_utils as payment_utils
from decimal import Decimal


salary_bp = Blueprint("salary_bp", __name__)

# ============================================================
# 💰 TRANG XEM LƯƠNG (Admin + HR) — FINAL SYNC WITH tinh_luong_nv()
# ============================================================
from core.salary_utils import tinh_luong_nv
from core.log_utils import ghi_lich_su
from datetime import datetime, date

@salary_bp.route("/salary")
@require_role("admin", "hr")
def salary_view():
    conn = get_sql_connection()
    conn.rollback()
    cursor = conn.cursor()

    # 📅 Lấy tháng/năm từ query string (hoặc mặc định tháng hiện tại)
    month = request.args.get("month", default=datetime.now().month, type=int)
    year = request.args.get("year", default=datetime.now().year, type=int)
    thang_nam = date(year, month, 1)
    print(f"[DEBUG] 🚀 Xem lương tháng {year}-{month:02d}")

    # 👤 Thông tin người xem
    role = session.get("role", "admin")
    username = session.get("username", "Hệ thống")
    ip_address = request.remote_addr or "Unknown"
    device_id = request.user_agent.string or "Unknown"

    # ============================================================
    # 1️⃣ Lấy toàn bộ nhân viên đang hoạt động
    # ============================================================
    cursor.execute("SELECT MaNV FROM NhanVien WHERE TrangThai = 1")
    all_nv = [r[0] for r in cursor.fetchall()]

    # ============================================================
    # 2️⃣ Tính lại (hoặc bổ sung) lương nếu chưa có trong DB
    # ============================================================
    for ma_nv in all_nv:
        cursor.execute("""
            SELECT 1 FROM Luong 
            WHERE MaNV=? AND MONTH(ThangNam)=? AND YEAR(ThangNam)=? AND DaXoa=1
        """, (ma_nv, month, year))
        has_salary = cursor.fetchone()
        if not has_salary:
            print(f"[AUTO] ⚙️ Chưa có lương DB cho {ma_nv} → Tính mới...")
            try:
                tinh_luong_nv(
                    cursor=cursor,
                    ma_nv=ma_nv,
                    thangnam=thang_nam,
                    nguoi_tinh=username,
                    save_to_db=True,
                    return_detail=False
                )
                conn.commit()
            except Exception as calc_err:
                print(f"[WARN] ⚠️ Không thể tính lương cho {ma_nv}: {calc_err}")
                conn.rollback()

    # ============================================================
    # 3️⃣ Tổng hợp lại dữ liệu lương sau khi đã cập nhật
    # ============================================================
    cursor.execute("SELECT COUNT(*) FROM NhanVien WHERE TrangThai = 1")
    total_employees = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT COUNT(DISTINCT L.MaNV)
        FROM Luong L
        JOIN NhanVien NV ON L.MaNV = NV.MaNV
        WHERE YEAR(L.ThangNam)=? AND MONTH(L.ThangNam)=? 
          AND L.DaXoa=1 AND L.TrangThai IN (1,2) AND NV.TrangThai=1
    """, (year, month))
    total_salaried = cursor.fetchone()[0] or 0
    total_unsalaried = max(total_employees - total_salaried, 0)

    cursor.execute("""
        SELECT SUM(L.TongTien)
        FROM Luong L
        JOIN NhanVien NV ON L.MaNV = NV.MaNV
        WHERE YEAR(L.ThangNam)=? AND MONTH(L.ThangNam)=?
          AND L.DaXoa=1 AND L.TrangThai IN (1,2) AND NV.TrangThai=1
    """, (year, month))
    total_salary = cursor.fetchone()[0] or 0

    # ============================================================
    # 4️⃣ Danh sách chi tiết lương (bản mới nhất)
    # ============================================================
    cursor.execute("""
        SELECT 
            NV.MaNV,
            NV.HoTen,
            PB.TenPB AS PhongBan,
            L.MaLuong,
            L.SoGioLam,
            L.TongTien AS TongTien
,
            L.TrangThai,
            CASE 
                WHEN L.TrangThai = 0 THEN N'Chưa tính'
                WHEN L.TrangThai = 1 THEN N'Đã tính'
                WHEN L.TrangThai = 2 THEN N'Đã thanh toán'
                ELSE N'Khác'
            END AS TrangThaiText,
            L.NgayThanhToan,
            L.PhuongThucChiTra,
            L.NguoiThanhToan
        FROM NhanVien NV
        LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
        OUTER APPLY (
            SELECT TOP 1 * FROM Luong L
            WHERE L.MaNV = NV.MaNV
              AND YEAR(L.ThangNam)=? AND MONTH(L.ThangNam)=? AND L.DaXoa=1
            ORDER BY L.TrangThai DESC, ISNULL(L.NgayThanhToan,L.NgayTinhLuong) DESC
        ) AS L
        WHERE NV.TrangThai=1
        ORDER BY NV.MaNV;
    """, (year, month))
    cols = [c[0] for c in cursor.description]
    salaries = [dict(zip(cols, row)) for row in cursor.fetchall()]

    # ============================================================
    # 5️⃣ Ghi log xem lương
    # ============================================================
    try:
        ghi_lich_su(
            ten_bang="Luong",
            ma_ban_ghi=None,
            hanh_dong="Xem danh sách lương",
            gia_tri_moi=f"Xem danh sách lương tháng {year}-{month:02d}",
            nguoi_thuc_hien=username,
            ip=ip_address,
            device=device_id,
            scope=f"Xem danh sách lương tháng {year}-{month:02d}"
        )
    except Exception as log_err:
        print(f"[WARN] ⚠️ Không thể ghi log xem danh sách lương: {log_err}")

    conn.close()

    # ============================================================
    # 6️⃣ Render template
    # ============================================================
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
# 💰 TÍNH LƯƠNG TOÀN BỘ NHÂN VIÊN — FINAL FIXED V5 (ĐỒNG BỘ & AN TOÀN FK)
# ============================================================
@salary_bp.route("/calculate_salary", methods=["POST", "GET"])
@require_role("admin", "hr")
def calculate_all_salary():
    """
    ✅ Tính lại toàn bộ lương tháng được chọn:
    - Gọi tinh_luong_nv() chuẩn từ salary_utils.py
    - Xoá sạch dữ liệu lương cũ (theo MaLuong) để tránh lỗi FK
    - Lưu DB + ghi log đầy đủ
    - Trả JSON nếu gọi AJAX hoặc flash khi gọi từ web
    """
    from datetime import datetime, date
    from core.salary_utils import tinh_luong_nv
    from core.log_utils import ghi_lich_su

    conn = get_sql_connection()
    cursor = conn.cursor()

    nguoi_tinh = session.get("username", "Hệ thống")
    ip_address = request.remote_addr or "Unknown"
    device_id = getattr(request.user_agent, "string", "Unknown")

    # 📅 Tháng/năm cần tính
    month = request.args.get("month", default=datetime.now().month, type=int)
    year = request.args.get("year", default=datetime.now().year, type=int)
    thang_nam = date(year, month, 1)
    scope_text = f"Tính lương tháng {thang_nam.strftime('%Y-%m')}"

    print(f"[DEBUG] 🚀 Bắt đầu tính lại toàn bộ lương ({nguoi_tinh}) | {scope_text}")

    try:
        # 1️⃣ Lấy danh sách nhân viên đang hoạt động
        cursor.execute("SELECT MaNV FROM NhanVien WHERE TrangThai = 1")
        nhanvien = [r[0] for r in cursor.fetchall()]
        if not nhanvien:
            msg = "⚠️ Không có nhân viên đang hoạt động để tính lương."
            ghi_lich_su("Luong", None, "Tính lương toàn bộ nhân viên", msg,
                        nguoi_tinh, ip_address, device_id, scope_text)
            flash(msg, "warning")
            return redirect(url_for("salary_bp.salary_view", month=month, year=year))

        # 2️⃣ Xoá dữ liệu cũ của tháng này (theo MaLuong để tránh lỗi FK)
        cursor.execute("""
            SELECT MaLuong FROM Luong
            WHERE YEAR(ThangNam)=? AND MONTH(ThangNam)=?
        """, (year, month))
        ma_luongs = [r[0] for r in cursor.fetchall()]

        if ma_luongs:
            # Xóa con trước
            cursor.executemany("DELETE FROM ChiTietLuong WHERE MaLuong = ?", [(m,) for m in ma_luongs])
            # Xóa cha sau
            cursor.executemany("DELETE FROM Luong WHERE MaLuong = ?", [(m,) for m in ma_luongs])
            conn.commit()
            print(f"[CLEAN] 🧹 Đã xoá toàn bộ dữ liệu lương cũ tháng {month}/{year}")

        # 3️⃣ Tính lại lương từng nhân viên
        da_tinh, loi_list = 0, []
        for ma_nv in nhanvien:
            try:
                tong_gio, tong_net = tinh_luong_nv(
                    cursor=cursor,
                    ma_nv=ma_nv,
                    thangnam=thang_nam,
                    nguoi_tinh=nguoi_tinh,
                    save_to_db=True,        # ✅ tự lưu DB vào Luong + ChiTietLuong
                    return_detail=False
                )
                conn.commit()
                da_tinh += 1
                print(f"[OK] 💰 {ma_nv}: {tong_gio:.2f}h | Net={tong_net:,.0f}đ")
            except Exception as e:
                conn.rollback()
                loi_list.append(f"{ma_nv}: {e}")
                print(f"[ERROR] ❌ {ma_nv}: {e}")

        # 4️⃣ Tổng kết kết quả
        if loi_list:
            msg = f"⚠️ Đã tính {da_tinh}/{len(nhanvien)} nhân viên. Có {len(loi_list)} lỗi:\n" + "\n".join(loi_list)
            success = False
        else:
            msg = f"✅ Đã tính lương thành công cho {da_tinh}/{len(nhanvien)} nhân viên."
            success = True

        # 5️⃣ Ghi log kết quả
        ghi_lich_su(
            ten_bang="Luong",
            ma_ban_ghi=None,
            hanh_dong="Tính lương toàn bộ nhân viên",
            gia_tri_moi=msg,
            nguoi_thuc_hien=nguoi_tinh,
            ip=ip_address,
            device=device_id,
            scope=scope_text
        )

        print(f"[DEBUG] 🧾 Kết quả tổng hợp: {msg}")
        if request.is_json or request.method == "POST":
            return jsonify({"success": success, "message": msg})
        else:
            flash(msg, "success" if success else "warning")
            return redirect(url_for("salary_bp.salary_view", month=month, year=year))

    except Exception as e:
        conn.rollback()
        import traceback; traceback.print_exc()
        print(f"[FATAL] ❌ Lỗi hệ thống khi tính lương: {e}")
        ghi_lich_su("Luong", None, "Lỗi khi tính lương toàn bộ nhân viên", str(e),
                    nguoi_tinh, ip_address, device_id, scope_text)

        if request.is_json or request.method == "POST":
            return jsonify({"success": False, "message": f"❌ Lỗi hệ thống: {e}"})
        flash(f"❌ Lỗi hệ thống khi tính lương: {e}", "danger")
        return redirect(url_for("salary_bp.salary_view", month=month, year=year))

    finally:
        cursor.close()
        conn.close()

# ============================================================
# 💰 TÍNH LƯƠNG RIÊNG CHO 1 NHÂN VIÊN — FINAL FIXED v6
# ============================================================

@salary_bp.route("/calculate_salary/<ma_nv>", methods=["POST", "GET"])
@require_role("admin", "hr")
def calculate_salary_for_one(ma_nv):
    """
    ✅ Tính lại lương cho 1 nhân viên theo tháng/năm đang chọn.
    - Xoá bản cũ theo MaLuong để tránh lỗi FK
    - Gọi tinh_luong_nv() chuẩn, lưu DB, ghi log
    - GET → flash, POST → JSON
    """
    from datetime import datetime, date
    from core.salary_utils import tinh_luong_nv
    from core.log_utils import ghi_lich_su

    conn = get_sql_connection()
    cursor = conn.cursor()

    nguoi_tinh = session.get("username", "Hệ thống")
    ip_address = request.remote_addr or "Unknown"
    device_id = getattr(request.user_agent, "string", "Unknown")

    month = request.args.get("month", default=datetime.now().month, type=int)
    year = request.args.get("year", default=datetime.now().year, type=int)
    thang_nam = date(year, month, 1)
    scope_text = f"Tính lương tháng {thang_nam.strftime('%Y-%m')}"

    print(f"[DEBUG] 🚀 Bắt đầu tính lương cho {ma_nv} ({nguoi_tinh}) | {scope_text}")

    try:
        # 1️⃣ Kiểm tra nhân viên hợp lệ
        cursor.execute("SELECT HoTen FROM NhanVien WHERE MaNV=? AND TrangThai=1", (ma_nv,))
        nv = cursor.fetchone()
        if not nv:
            msg = f"⚠️ Không tìm thấy nhân viên {ma_nv} hoặc đã nghỉ việc."
            if request.is_json or request.method == "POST":
                return jsonify({"success": False, "message": msg})
            flash(msg, "warning")
            return redirect(url_for("salary_bp.salary_view", month=month, year=year))
        ho_ten = nv[0]

        # 2️⃣ Xoá dữ liệu cũ theo MaLuong để tránh lỗi FK
        ma_luong = f"L{ma_nv}_{year}{month:02d}"
        cursor.execute("DELETE FROM ChiTietLuong WHERE MaLuong = ?", (ma_luong,))
        cursor.execute("DELETE FROM Luong WHERE MaLuong = ?", (ma_luong,))
        conn.commit()
        print(f"[CLEAN] 🧹 Đã xoá dữ liệu lương cũ {ma_luong}")

        # 3️⃣ Tính lại lương mới theo công thức chuẩn
        tong_gio, tong_net, chi_tiet = tinh_luong_nv(
            cursor=cursor,
            ma_nv=ma_nv,
            thangnam=thang_nam,
            nguoi_tinh=nguoi_tinh,
            save_to_db=True,
            return_detail=True
        )
        conn.commit()
        print(f"[OK] 💰 {ma_nv}: {tong_gio:.2f}h | Net={tong_net:,.0f}đ")

        # 4️⃣ Ghi log
        msg = f"✅ Đã tính lại lương cho {ho_ten} ({ma_nv}) tháng {month:02d}/{year}: {tong_gio:.2f}h, thực lĩnh {tong_net:,.0f}₫"
        ghi_lich_su(
            ten_bang="Luong",
            ma_ban_ghi=ma_nv,
            hanh_dong="Tính lương nhân viên",
            gia_tri_moi=msg,
            nguoi_thuc_hien=nguoi_tinh,
            ip=ip_address,
            device=device_id,
            scope=scope_text
        )

        # 5️⃣ Trả phản hồi
        if request.is_json or request.method == "POST":
            return jsonify({"success": True, "message": msg, "chi_tiet": chi_tiet})
        flash(msg, "success")
        return redirect(url_for("salary_bp.salary_view", month=month, year=year))

    except Exception as e:
        conn.rollback()
        err_msg = f"❌ Lỗi khi tính lương cho {ma_nv}: {e}"
        print(f"[ERROR] {err_msg}")
        import traceback; traceback.print_exc()
        try:
            ghi_lich_su(
                ten_bang="Luong",
                ma_ban_ghi=ma_nv,
                hanh_dong="Lỗi tính lương nhân viên",
                gia_tri_moi=str(e),
                nguoi_thuc_hien=nguoi_tinh,
                ip=ip_address,
                device=device_id,
                scope=scope_text
            )
        except:
            pass
        if request.is_json or request.method == "POST":
            return jsonify({"success": False, "message": err_msg})
        flash(err_msg, "danger")
        return redirect(url_for("salary_bp.salary_view", month=month, year=year))

    finally:
        cursor.close()
        conn.close()

# ============================================================
# 💰 XEM CHI TIẾT LƯƠNG NHÂN VIÊN — FINAL FIXED V7 (ĐỒNG BỘ VỚI HÀM TÍNH V18)
# ============================================================
@salary_bp.route("/salary/<ma_nv>")
@require_role("admin", "hr")
def salary_detail(ma_nv):
    """
    ✅ Hiển thị chi tiết lương 1 nhân viên
    ------------------------------------------------------------
    - Đồng bộ với tinh_luong_nv() FINAL V18
    - Tự động gọi tính lương, không lưu DB khi chỉ xem
    - Truyền đầy đủ dữ liệu phụ cấp, khấu trừ, gross, net sang template
    - Ghi log hành động xem chi tiết
    ------------------------------------------------------------
    """

    from datetime import date
    conn = get_sql_connection()
    cursor = conn.cursor()

    role = session.get("role", "admin")
    nguoi_xem = session.get("username", "Hệ thống")
    ip_address = request.remote_addr or "Unknown"
    device_id = request.user_agent.string or "Unknown"

    # 📅 Tháng/năm đang xem
    month = request.args.get("month", default=date.today().month, type=int)
    year = request.args.get("year", default=date.today().year, type=int)
    thang_nam = date(year, month, 1)
    scope_text = f"Xem chi tiết lương tháng {year}-{month:02d}"

    try:
        # 1️⃣ Lấy thông tin nhân viên
        cursor.execute("""
            SELECT NV.MaNV, NV.HoTen, NV.ChucVu, PB.TenPB, NV.SoCaPhepConLai
            FROM NhanVien NV
            LEFT JOIN PhongBan PB ON NV.MaPB = PB.MaPB
            WHERE NV.MaNV = ?
        """, (ma_nv,))
        emp = cursor.fetchone()
        if not emp:
            return render_template("error.html", message=f"❌ Không tìm thấy nhân viên {ma_nv}")

        # 2️⃣ Gọi hàm tính lương chi tiết (không lưu DB)
        tong_gio, net, chi_tiet, luong_chinh, gross = tinh_luong_nv(
            cursor=cursor,
            ma_nv=ma_nv,
            thangnam=thang_nam,
            nguoi_tinh=nguoi_xem,
            save_to_db=False,
            return_detail=True
        )

        # ⚙️ Tính lại phụ cấp & khấu trừ (giống V18)
        from decimal import Decimal
        params = get_tham_so_luong(cursor)
        dec = lambda k, d: Decimal(str(params.get(k, d)))

        # Số ca làm / vắng để tính phụ cấp & thưởng
        so_ca_di_lam = sum(1 for r in chi_tiet if r["TrangThai"] in (1, 2))
        so_ca_vang = sum(1 for r in chi_tiet if r["TrangThai"] == 0)
        tong_ca = len(chi_tiet)
        ty_le = (so_ca_di_lam / tong_ca) if tong_ca else 0

        # Phụ cấp
        phu_cap_xang = dec("PhuCapXangXe", 500_000)
        phu_cap_an = dec("PhuCapAnTrua", 30_000) * Decimal(so_ca_di_lam)
        phu_cap_khac = dec("PhuCapKhac", 200_000)
        thuong_chuyen_can = dec("ThuongChuyenCan", 300_000) if (so_ca_vang == 0 and ty_le >= 0.95) else Decimal('0')
        tong_phu_cap = phu_cap_xang + phu_cap_an + phu_cap_khac + thuong_chuyen_can

        # Khấu trừ bảo hiểm + thuế (giống hàm)
        tong_khau_tru_bh = dec("KhauTru_BHXH", 0.08) + dec("KhauTru_BHYT", 0.015) + dec("KhauTru_BHTN", 0.01)
        bao_hiem = (Decimal(gross) * tong_khau_tru_bh).quantize(Decimal('1.'))
        tnct = float(Decimal(gross) - bao_hiem - Decimal('11000000'))
        pit = 0
        if tnct > 0:
            brackets = [(5_000_000, 0.05), (5_000_000, 0.10), (8_000_000, 0.15),
                        (14_000_000, 0.20), (20_000_000, 0.25), (28_000_000, 0.30), (float('inf'), 0.35)]
            for limit, rate in brackets:
                if tnct <= 0: break
                taxable = min(tnct, limit)
                pit += taxable * rate
                tnct -= taxable

        pit = Decimal(pit).quantize(Decimal('1.'))
        net_calc = (Decimal(gross) - bao_hiem - pit).quantize(Decimal('1.'))

        # 3️⃣ Ghi log xem lương
        ghi_lich_su(
            ten_bang="Luong",
            ma_ban_ghi=ma_nv,
            hanh_dong="Xem chi tiết lương nhân viên",
            gia_tri_moi=f"Xem chi tiết lương {ma_nv} tháng {month:02d}/{year} | Gross={gross:,.0f} | Net={net_calc:,.0f}",
            nguoi_thuc_hien=nguoi_xem,
            ip=ip_address,
            device=device_id,
            scope=scope_text
        )

        # 4️⃣ Render ra template (đủ biến cho phần tổng hợp)
        template_name = "hr_salary_detail.html" if role == "hr" else "salary_detail.html"
        return render_template(
            template_name,
            emp=emp,
            records=chi_tiet,
            luong_chinh=float(luong_chinh),
            gross=float(gross),
            net=float(net_calc),
            tong_gio=float(tong_gio),
            current_month=month,
            current_year=year,
            role_label="Nhân viên",
            # --- Phụ cấp & thưởng ---
            phu_cap_xang=float(phu_cap_xang),
            phu_cap_an=float(phu_cap_an),
            phu_cap_khac=float(phu_cap_khac),
            thuong_chuyen_can=float(thuong_chuyen_can),
            tong_phu_cap=float(tong_phu_cap),
            # --- Khấu trừ ---
            bao_hiem=float(bao_hiem),
            pit=float(pit)
        )

    except Exception as e:
        print(f"[ERROR] ❌ Lỗi xem chi tiết lương {ma_nv}: {e}")
        return render_template("error.html", message=f"Lỗi khi xem chi tiết lương: {e}")

    finally:
        cursor.close()
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

# 🔎 LẤY THÔNG TIN THANH TOÁN CHO 1 BẢN LƯƠNG
# ============================================================
@salary_bp.route("/salary/<string:ma_luong>/payment-info", methods=["GET"])
@require_role("admin", "hr")
def get_payment_info(ma_luong: str):
    """
    ✅ Trả về thông tin cần thiết để hiển thị modal thanh toán.
    - Kiểm tra trạng thái lương (chưa tính / đã thanh toán)
    - Ghi log hành động xem thông tin thanh toán
    - Trả thông tin nhân viên và lương để hiển thị modal
    """
    conn = get_sql_connection()
    cursor = conn.cursor()
    nguoi_thuc_hien = session.get("username", "Hệ thống")
    ip = request.remote_addr or "Unknown"
    device = request.user_agent.string or "Unknown"

    try:
        # ============================================================
        # 🧾 Lấy thông tin lương + nhân viên
        # ============================================================
        cursor.execute("""
            SELECT 
                L.MaLuong, L.MaNV, L.SoGioLam, L.TongTien, L.TrangThai, 
                L.NgayTinhLuong, L.NguoiTinhLuong, L.NgayThanhToan, L.GhiChu,
                L.PhuongThucChiTra, L.SoTaiKhoan, L.NganHang, L.PhiGiaoDich,
                 L.ThangNam, L.NguoiThanhToan,
                N.HoTen, N.Email
            FROM Luong L
            LEFT JOIN NhanVien N ON L.MaNV = N.MaNV
            WHERE L.MaLuong = ?
        """, (ma_luong,))
        row = cursor.fetchone()

        if not row:
            return jsonify({
                "success": False,
                "message": f"Không tìm thấy bản lương {ma_luong}."
            }), 404

        # ============================================================
        # 🧱 Chuyển kết quả thành dict
        # ============================================================
        cols = [
            "MaLuong","MaNV","SoGioLam","TongTien","TrangThai",
            "NgayTinhLuong","NguoiTinhLuong","NgayThanhToan","GhiChu",
            "PhuongThucChiTra","SoTaiKhoan","NganHang","PhiGiaoDich","ThangNam","NguoiThanhToan",
            "HoTen","Email"
        ]
        data = {c: row[i] for i, c in enumerate(cols)}

        # ============================================================
        # 🚫 Kiểm tra trạng thái để chặn thao tác
        # ============================================================
        if data["TrangThai"] == 0:
            return jsonify({
                "success": False,
                "message": f"⚠️ Bảng lương {ma_luong} chưa được tính. Vui lòng tính lương trước khi thanh toán."
            }), 400

        if data["TrangThai"] == 2:
            return jsonify({
                "success": False,
                "message": f"❌ Bảng lương {ma_luong} đã được thanh toán. Hãy xóa và tính lại trước khi thanh toán lại."
            }), 400

        # ============================================================
        # 🔤 Hiển thị trạng thái chữ
        # ============================================================
        data["TrangThaiText"] = (
            "Chưa tính" if data["TrangThai"] == 0
            else "Đã tính" if data["TrangThai"] == 1
            else "Đã thanh toán"
        )

        # ============================================================
        # 🧾 Ghi log hành động "Xem thông tin thanh toán"
        # ============================================================
        try:
            ghi_lich_su(
                ten_bang="Luong",
                ma_ban_ghi=ma_luong,
                hanh_dong="Xem thông tin thanh toán",
                gia_tri_moi=f"Xem chi tiết thanh toán cho {data['HoTen']} ({ma_luong})",
                nguoi_thuc_hien=nguoi_thuc_hien,
                ip=ip,
                device=device,
                scope="PAYMENT_VIEW"
            )
        except Exception as log_err:
            print(f"[WARN] ⚠️ Không ghi được log xem thanh toán: {log_err}")

        # ============================================================
        # ✅ Trả dữ liệu hợp lệ để hiển thị modal thanh toán
        # ============================================================
        return jsonify({
            "success": True,
            "data": data
        })

    except Exception as e:
        print(f"[ERROR] ❌ get_payment_info: {e}")
        import traceback; traceback.print_exc()
        return jsonify({
            "success": False,
            "message": f"Lỗi khi lấy thông tin thanh toán: {e}"
        }), 500

    finally:
        cursor.close()
        conn.close()
# ============================================================
# 1️⃣ KHỞI TẠO THANH TOÁN LƯƠNG (Admin tạo giao dịch Pending + Gửi OTP)
# ============================================================
@salary_bp.route("/pay/<ma_luong>", methods=["POST"])
@require_role("admin", "hr")
def pay_salary_start(ma_luong):
    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")
    user_id = session.get("user_id", 1)  # ✅ Dùng user_id (int)
    ip = request.remote_addr
    device = request.user_agent.string[:500]

    # 🔐 Chỉ admin mới được thanh toán
    role = session.get("role", "")
    if role != "admin":
        return jsonify({
            "success": False,
            "message": "Chỉ tài khoản Admin mới được phép thực hiện thanh toán lương."
        }), 403

    # ============================================================
    # 🔎 Lấy dữ liệu lương cần thanh toán
    # ============================================================
    cursor.execute("""
        SELECT L.MaNV, L.TongTien, N.HoTen, N.Email
        FROM Luong L 
        JOIN NhanVien N ON L.MaNV = N.MaNV
        WHERE L.MaLuong = ?
    """, ma_luong)
    row = cursor.fetchone()
    if not row:
        return jsonify({"success": False, "message": "Không tìm thấy bản ghi lương."}), 404

    ma_nv, so_tien, ten_nv, email_nv = row
    so_tien = Decimal(str(so_tien))
    phuong_thuc = request.form.get("phuong_thuc", "bank")
    phi = calc_fee(phuong_thuc, so_tien)

    # ============================================================
    # 🧾 Tạo giao dịch tạm (Pending-OTP)
    # ============================================================
    ma_gd_temp = payment_utils.generate_txid(prefix="PEND")
    noi_dung = f"Thanh toán tạm (chờ OTP) qua {phuong_thuc}"
    try:
        cursor.execute("""
            INSERT INTO GiaoDichLuong (MaLuong, MaNV, SoTien, PhuongThuc, PhiGiaoDich, NoiDung,
                                       NgayGiaoDich, TrangThai, MaGiaoDich, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?, ?, ?)
        """, (
            ma_luong, ma_nv, float(so_tien), phuong_thuc,
            float(phi), noi_dung, "Pending-OTP", ma_gd_temp, username
        ))
        conn.commit()

        ghi_lich_su(
            ten_bang="GiaoDichLuong",
            ma_ban_ghi=ma_gd_temp,
            hanh_dong="Khởi tạo thanh toán (Pending-OTP)",
            gia_tri_moi=f"{ma_luong} - {ma_nv} - {so_tien:,}đ qua {phuong_thuc}",
            nguoi_thuc_hien=username,
            ip=ip,
            device=device,
            scope="PAYMENT_INIT"
        )
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "message": f"Lỗi tạo giao dịch tạm: {e}"}), 500

    # ============================================================
    # 🔢 Tạo OTP (5 phút)
    # ============================================================
    otp = payment_utils.generate_otp(6)
    expires = payment_utils.otp_expires_at(minutes=5)

    try:
        cursor.execute("""
            IF OBJECT_ID('dbo.TempOTP', 'U') IS NULL
            CREATE TABLE TempOTP (
                MaGiaoDich NVARCHAR(50) PRIMARY KEY,
                OTP NVARCHAR(10),
                ExpiresAt DATETIME
            )
        """)
        cursor.execute("""
            MERGE TempOTP AS T
            USING (SELECT ? AS MaGiaoDich) AS S
            ON T.MaGiaoDich = S.MaGiaoDich
            WHEN MATCHED THEN UPDATE SET OTP = ?, ExpiresAt = ?
            WHEN NOT MATCHED THEN INSERT (MaGiaoDich, OTP, ExpiresAt)
            VALUES (?, ?, ?);
        """, (ma_gd_temp, otp, expires, ma_gd_temp, otp, expires))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print("[WARN] Lưu OTP lỗi:", e)

    # ============================================================
    # ✉️ Gửi OTP tới email của ADMIN
    # ============================================================
    cursor.execute("SELECT Email FROM TaiKhoan WHERE TenDangNhap = ?", username)
    row_admin = cursor.fetchone()
    email_admin = row_admin[0] if row_admin and row_admin[0] else None

    subject = f"[OTP] Xác nhận thanh toán lương - Mã tạm {ma_gd_temp}"
    body = (
        f"Xin chào {username},\n\n"
        f"Mã OTP để xác nhận thanh toán là: {otp}\n"
        f"Mã này có hiệu lực trong 5 phút.\n\n"
        f"Thực hiện thanh toán lương cho nhân viên {ten_nv or ma_nv}, "
        f"số tiền: {so_tien:,.0f}đ.\n\n"
        f"Trân trọng,\nFaceID System"
    )

    if email_admin:
        ok, err = send_email_with_attachment(email_admin, subject, body)
        print(f"[EMAIL INFO] 📧 Gửi OTP tới {email_admin} | OTP={otp}")
    else:
        ok, err = True, None
        print(f"[OTP DEMO] 🔐 Không có email admin. OTP cho {username}: {otp}")

    # ============================================================
    # 🧾 Lưu lịch sử gửi mail OTP
    # ============================================================
    try:
        status = 1 if ok else 0
        cursor.execute("""
            INSERT INTO LichSuEmail (MaTK, EmailTo, LoaiThongBao, ThoiGian, TrangThai, MaThamChieu)
            VALUES (?, ?, ?, GETDATE(), ?, ?)
        """, (user_id, email_admin or "(demo)", 'OTP-Payment', status, ma_gd_temp))  # ✅ Dùng user_id thay vì username
        conn.commit()

        ghi_lich_su(
            ten_bang="LichSuEmail",
            ma_ban_ghi=ma_gd_temp,
            hanh_dong="Gửi OTP thanh toán",
            gia_tri_moi=f"Gửi OTP {otp} tới {email_admin or 'console'}",
            nguoi_thuc_hien=username,
            ip=ip,
            device=device,
            scope="OTP_SEND"
        )
    except Exception as e:
        conn.rollback()
        print("[WARN] Không thể ghi log email OTP:", e)

    # ============================================================
    # ✅ Trả kết quả về client
    # ============================================================
    return jsonify({
        "success": True,
        "need_otp": True,
        "ma_gd_temp": ma_gd_temp,
        "message": f"Đã gửi OTP xác nhận tới {email_admin or 'console (demo)'}. Vui lòng nhập mã OTP để hoàn tất."
    })

# ============================================================
# ✅ XÁC THỰC OTP & HOÀN TẤT THANH TOÁN LƯƠNG
# ============================================================
@salary_bp.route("/pay/verify", methods=["POST"])
@require_role("admin", "hr")
def pay_salary_verify():
    data = request.get_json() or {}
    ma_gd_temp = data.get("ma_gd")
    otp_submitted = data.get("otp")
    so_tai_khoan = data.get("so_tai_khoan")
    ngan_hang = data.get("ngan_hang")

    username = session.get("username", "Hệ thống")
    user_id = session.get("user_id", 1)
    role = session.get("role", "")
    ip = request.remote_addr
    device = request.user_agent.string[:500]

    # ------------------------------------------------------------
    # 🚫 Chỉ admin được xác nhận OTP và hoàn tất thanh toán
    # ------------------------------------------------------------
    if role != "admin":
        return jsonify({
            "success": False,
            "message": "Chỉ tài khoản Admin mới được xác nhận và hoàn tất thanh toán lương."
        }), 403

    if not ma_gd_temp or not otp_submitted:
        return jsonify({"success": False, "message": "Thiếu mã giao dịch hoặc OTP."}), 400

    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        # ======================================================
        # 🔐 KIỂM TRA OTP HỢP LỆ (đã gửi cho admin)
        # ======================================================
        cursor.execute("SELECT OTP, ExpiresAt FROM TempOTP WHERE MaGiaoDich = ?", ma_gd_temp)
        row = cursor.fetchone()
        if not row:
            return jsonify({"success": False, "message": "OTP không tồn tại hoặc đã hết hạn."}), 400

        otp_real, expires_at = row
        if datetime.utcnow() > expires_at or otp_submitted != otp_real:
            return jsonify({"success": False, "message": "OTP sai hoặc đã hết hạn."}), 400

        # ======================================================
        # 🔎 LẤY GIAO DỊCH CHỜ XÁC NHẬN
        # ======================================================
        cursor.execute("""
            SELECT MaLuong, MaNV, SoTien, PhuongThuc, PhiGiaoDich
            FROM GiaoDichLuong
            WHERE MaGiaoDich = ? AND TrangThai = 'Pending-OTP'
        """, ma_gd_temp)
        gd = cursor.fetchone()
        if not gd:
            return jsonify({"success": False, "message": "Giao dịch không hợp lệ hoặc đã xử lý."}), 400

        ma_luong, ma_nv, so_tien, phuong_thuc, phi = gd

        # 🧱 Chặn thanh toán trùng
        cursor.execute("SELECT TrangThai FROM Luong WHERE MaLuong = ?", ma_luong)
        row_tt = cursor.fetchone()
        if row_tt and str(row_tt[0]) == "2":
            return jsonify({"success": False, "message": "Bảng lương này đã được thanh toán."}), 400

        # ======================================================
        # 💳 GIẢ LẬP THANH TOÁN THẬT
        # ======================================================
        result = payment_utils.fake_payment_gateway(phuong_thuc, Decimal(str(so_tien)))
        if not result.get("success"):
            cursor.execute("""
                UPDATE GiaoDichLuong
                SET TrangThai = 'Failed', NoiDung = ?
                WHERE MaGiaoDich = ?
            """, (f"Lỗi gateway: {result.get('error')}", ma_gd_temp))
            conn.commit()
            return jsonify({"success": False, "message": "Thanh toán thất bại tại gateway."}), 500

        txid_real = result.get("txid")

        # ======================================================
        # 💾 CẬP NHẬT BẢNG LƯƠNG (ĐÃ THANH TOÁN)
        # ======================================================
        cursor.execute("""
            UPDATE Luong
            SET TrangThai = 2,
                NgayThanhToan = GETDATE(),
                NguoiThanhToan = ?,
                MaTK = ?,
                PhuongThucChiTra = ?,
                SoTaiKhoan = ?,
                NganHang = ?,
                PhiGiaoDich = ?,
                GhiChu = N'Thanh toán thành công',
                DaXoa = 1
            WHERE MaLuong = ?
        """, (
            username,
            user_id,
            phuong_thuc,
            so_tai_khoan,
            ngan_hang,
            float(phi),
            ma_luong
        ))
        conn.commit()
        print(f"[PAYMENT] ✅ Đã cập nhật Luong.TrangThai=2, DaXoa=1 cho {ma_luong}")

        # ======================================================
        # 🧩 CẬP NHẬT THÔNG TIN NGÂN HÀNG NHÂN VIÊN
        # ======================================================
        try:
            if so_tai_khoan or ngan_hang or phuong_thuc:
                cursor.execute("""
                    UPDATE NhanVien
                    SET 
                        SoTaiKhoan = CASE WHEN ? <> '' THEN ? ELSE SoTaiKhoan END,
                        NganHang = CASE WHEN ? <> '' THEN ? ELSE NganHang END,
                        PhuongThucMacDinh = CASE WHEN ? <> '' THEN ? ELSE PhuongThucMacDinh END
                    WHERE MaNV = ?
                """, (
                    so_tai_khoan, so_tai_khoan,
                    ngan_hang, ngan_hang,
                    phuong_thuc, phuong_thuc,
                    ma_nv
                ))
                conn.commit()
                print(f"[SYNC] 🔄 Đã cập nhật thông tin ngân hàng cho {ma_nv}")
        except Exception as e:
            conn.rollback()
            print(f"[WARN] ⚠️ Không thể cập nhật thông tin NhanVien: {e}")

        # ======================================================
        # 🧾 CẬP NHẬT GIAO DỊCH
        # ======================================================
        cursor.execute("""
            UPDATE GiaoDichLuong
            SET TrangThai = 'Thành công',
                MaGiaoDich = ?,
                NgayGiaoDich = GETDATE(),
                NoiDung = CONCAT(N'Thanh toán hoàn tất cho ', ?, N' qua ', ?)
            WHERE MaGiaoDich = ?
        """, (txid_real, ma_nv, phuong_thuc, ma_gd_temp))
        conn.commit()

        # ======================================================
        # 🧹 XÓA OTP TẠM
        # ======================================================
        cursor.execute("DELETE FROM TempOTP WHERE MaGiaoDich = ?", ma_gd_temp)
        conn.commit()

        # ======================================================
        # 🧾 TẠO BIÊN LAI PDF (TỰ ĐỘNG LẤY STK & NGÂN HÀNG)
        # ======================================================
        cursor.execute("""
            SELECT HoTen, Email, SoTaiKhoan, NganHang, PhuongThucMacDinh
            FROM NhanVien
            WHERE MaNV = ?
        """, ma_nv)
        row_nv = cursor.fetchone()
        ten_nv, email_to, so_tk_nv, ngan_hang_nv, phuong_thuc_nv = row_nv if row_nv else ("", None, "", "", "")

        # Ưu tiên thông tin nhập tay nếu có
        so_tk_final = so_tai_khoan or so_tk_nv
        ngan_hang_final = ngan_hang or ngan_hang_nv
        phuong_thuc_final = phuong_thuc or phuong_thuc_nv or "bank"

        signature_path = os.path.join(current_app.root_path, "static", "images", "signature_fake.png")

        pdf_path = payment_utils.generate_salary_pdf(
            txid=txid_real,
            ma_nv=ma_nv,
            ho_ten=ten_nv,
            so_tien=Decimal(str(so_tien)),
            phuong_thuc=phuong_thuc_final,
            phi=Decimal(str(phi)),
            file_path=None,
            signature_img_path=signature_path,
            qr_target=f"https://faceid.local/receipts/{txid_real}",
            so_tk=so_tk_final,              # ✅ truyền STK
            ngan_hang=ngan_hang_final       # ✅ truyền Ngân hàng
        )

        print(f"[PDF] ✅ Biên lai có STK={so_tk_final}, NH={ngan_hang_final}: {pdf_path}")

        cursor.execute("""
            UPDATE GiaoDichLuong
            SET NoiDung = CONCAT(ISNULL(NoiDung, ''), ' | PDF=', ?)
            WHERE MaGiaoDich = ?
        """, (pdf_path, txid_real))
        conn.commit()

        # ======================================================
        # ✉️ GỬI EMAIL BIÊN LAI CHO NHÂN VIÊN
        # ======================================================
        if email_to:
            subject = f"Biên lai thanh toán lương - FaceID - Mã {txid_real}"
            body = (
                f"Xin chào {ten_nv or ma_nv},\n\n"
                f"Hệ thống FaceID đã thực hiện thanh toán lương thành công qua {phuong_thuc}.\n"
                f"Vui lòng xem biên lai đính kèm.\n\nTrân trọng,\nFaceID System"
            )
            ok, _ = send_email_with_attachment(email_to, subject, body, attachment_path=pdf_path)

            cursor.execute("""
                INSERT INTO LichSuEmail (MaTK, EmailTo, LoaiThongBao, ThoiGian, TrangThai, MaThamChieu)
                VALUES (?, ?, ?, GETDATE(), ?, ?)
            """, (user_id, email_to, 'PAYMENT_RECEIPT', 1 if ok else 0, ma_luong))
            conn.commit()

        # ======================================================
        # 🧠 GHI LỊCH SỬ HỆ THỐNG
        # ======================================================
        ghi_lich_su(
            ten_bang="Luong",
            ma_ban_ghi=ma_luong,
            hanh_dong="Hoàn tất thanh toán",
            gia_tri_moi=f"TX={txid_real}, PhuongThuc={phuong_thuc}, SoTK={so_tai_khoan}, NH={ngan_hang}",
            nguoi_thuc_hien=username,
            ip=ip,
            device=device,
            scope="PAYMENT_COMPLETE"
        )

        # ======================================================
        # ✅ TRẢ KẾT QUẢ
        # ======================================================
        return jsonify({
            "success": True,
            "message": f"Thanh toán thành công qua {phuong_thuc}.",
            "transaction_id": txid_real,
            "pdf": pdf_path
        })

    except Exception as e:
        conn.rollback()
        print("[ERROR] ❌ pay_salary_verify:", e)
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "message": f"Lỗi khi hoàn tất thanh toán: {e}"}), 500

    finally:
        cursor.close()
        conn.close()

# ============================================================
# 🏦 LẤY THÔNG TIN NGÂN HÀNG / PHƯƠNG THỨC MẶC ĐỊNH CỦA NHÂN VIÊN
# ============================================================
@salary_bp.route("/employee/bank-info/<ma_nv>", methods=["GET"])
@require_role("admin", "hr")
def get_employee_bank_info(ma_nv):
    conn = get_sql_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT 
                ISNULL(SoTaiKhoan, '') AS SoTaiKhoan,
                ISNULL(NganHang, '') AS NganHang,
                ISNULL(PhuongThucMacDinh, '') AS PhuongThucMacDinh
            FROM NhanVien
            WHERE MaNV = ?
        """, (ma_nv,))
        row = cursor.fetchone()

        if not row:
            return jsonify({"success": False, "message": "Không tìm thấy nhân viên."}), 404

        so_tk, ngan_hang, phuong_thuc = row

        # 🧾 Ghi log truy vấn
        try:
            ghi_lich_su(
                ten_bang="NhanVien",
                ma_ban_ghi=ma_nv,
                hanh_dong="Xem thông tin ngân hàng",
                gia_tri_moi=f"SoTK={so_tk}, NH={ngan_hang}, PT={phuong_thuc}",
                nguoi_thuc_hien=session.get("username", "Hệ thống"),
                ip=request.remote_addr,
                device=request.user_agent.string,
                scope="BANK_INFO_VIEW"
            )
        except Exception as log_err:
            print(f"[WARN] ⚠️ Không thể ghi log bank-info: {log_err}")

        return jsonify({
            "success": True,
            "so_tai_khoan": so_tk,
            "ngan_hang": ngan_hang,
            "phuong_thuc": phuong_thuc
        })

    except Exception as e:
        print("[ERROR] ❌ get_employee_bank_info:", e)
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "message": f"Lỗi khi truy xuất thông tin ngân hàng: {e}"}), 500

    finally:
        cursor.close()
        conn.close()

# ============================================================
# ♻️ HOÀN TIỀN GIẢ LẬP CHO GIAO DỊCH LƯƠNG
# ============================================================
@salary_bp.route("/admin/refund/<ma_gd>", methods=["POST"])
@require_role("admin")
def refund_transaction(ma_gd):
    conn = get_sql_connection()
    cursor = conn.cursor()
    username = session.get("username", "Hệ thống")
    user_id = session.get("user_id", 1)
    ip = request.remote_addr
    device = request.user_agent.string[:500]

    try:
        # ======================================================
        # 🔍 LẤY GIAO DỊCH GỐC
        # ======================================================
        cursor.execute("""
            SELECT MaLuong, MaNV, SoTien, PhuongThuc, PhiGiaoDich, TrangThai
            FROM GiaoDichLuong WHERE MaGiaoDich = ?
        """, (ma_gd,))
        r = cursor.fetchone()
        if not r:
            return jsonify({"success": False, "message": "Không tìm thấy giao dịch."}), 404

        ma_luong, ma_nv, so_tien, phuong_thuc, phi, trangthai = r

        if trangthai != "Thành công":
            return jsonify({"success": False, "message": "Giao dịch chưa hoàn tất hoặc đã hoàn tiền."}), 400

        ma_gd_refund = payment_utils.generate_txid(prefix="RFND")

        # ======================================================
        # 💸 TẠO BẢN GHI HOÀN TIỀN
        # ======================================================
        noi_dung = f"Hoàn tiền cho giao dịch {ma_gd} ({ma_nv})"
        cursor.execute("""
            INSERT INTO GiaoDichLuong 
                (MaLuong, MaNV, SoTien, PhuongThuc, PhiGiaoDich,
                 NoiDung, NgayGiaoDich, TrangThai, MaGiaoDich, NguoiThucHien)
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?, ?, ?)
        """, (
            ma_luong,
            ma_nv,
            -abs(float(so_tien)),       # âm để biểu diễn hoàn tiền
            phuong_thuc,                # hoàn đúng kênh gốc
            float(phi),
            noi_dung,
            "Refunded",
            ma_gd_refund,
            username
        ))

        # ======================================================
        # 💾 CẬP NHẬT GIAO DỊCH GỐC + BẢNG LƯƠNG
        # ======================================================
        cursor.execute("""
            UPDATE GiaoDichLuong
            SET TrangThai = 'Refunded'
            WHERE MaGiaoDich = ?
        """, (ma_gd,))

        cursor.execute("""
            UPDATE Luong
            SET TrangThai = 0,
                NgayThanhToan = NULL,
                NguoiThanhToan = NULL,
                PhuongThucChiTra = NULL,
                PhiGiaoDich = NULL,
                GhiChu = CONCAT(N'Đã hoàn tiền cho giao dịch ', ?),
                DaXoa = 0
            WHERE MaLuong = ?
        """, (ma_gd_refund, ma_luong))
        conn.commit()

        # ======================================================
        # 🧾 TẠO BIÊN LAI HOÀN TIỀN (PDF)
        # ======================================================
        cursor.execute("SELECT HoTen, Email FROM NhanVien WHERE MaNV = ?", (ma_nv,))
        nv = cursor.fetchone()
        ten_nv, email_to = nv if nv else ("", None)

        signature_path = os.path.join(current_app.root_path, "static", "images", "signature_fake.png")
        pdf_path = payment_utils.generate_salary_pdf(
            ma_gd_refund,
            ma_nv,
            ten_nv,
            Decimal(str(abs(so_tien))),  # số tiền dương trong biên lai
            phuong_thuc,
            Decimal(str(phi)),
            file_path=None,
            signature_img_path=signature_path,
            is_refund=True  # nếu generate_salary_pdf hỗ trợ flag này
        )

        cursor.execute("""
            UPDATE GiaoDichLuong
            SET NoiDung = CONCAT(ISNULL(NoiDung,''), ' | PDF=', ?)
            WHERE MaGiaoDich = ?
        """, (pdf_path, ma_gd_refund))
        conn.commit()

        # ======================================================
        # ✉️ GỬI EMAIL XÁC NHẬN HOÀN TIỀN
        # ======================================================
        if email_to:
            subject = f"[Refund] Xác nhận hoàn tiền lương - Mã {ma_gd_refund}"
            body = (
                f"Xin chào {ten_nv or ma_nv},\n\n"
                f"Hệ thống FaceID đã hoàn tiền lương cho giao dịch {ma_gd}.\n"
                f"Số tiền hoàn: {abs(float(so_tien)):,}đ qua {phuong_thuc}.\n"
                f"Vui lòng xem biên lai đính kèm.\n\n"
                f"Trân trọng,\nFaceID System"
            )
            ok, _ = send_email_with_attachment(email_to, subject, body, attachment_path=pdf_path)

            cursor.execute("""
                INSERT INTO LichSuEmail (MaTK, EmailTo, LoaiThongBao, ThoiGian, TrangThai, MaThamChieu)
                VALUES (?, ?, ?, GETDATE(), ?, ?)
            """, (user_id, email_to, 'PAYMENT_REFUND', 1 if ok else 0, ma_luong))
            conn.commit()

        # ======================================================
        # 🧠 GHI LỊCH SỬ HỆ THỐNG
        # ======================================================
        ghi_lich_su(
            ten_bang="GiaoDichLuong",
            ma_ban_ghi=ma_gd_refund,
            hanh_dong="Hoàn tiền giả lập",
            gia_tri_moi=f"Hoàn {abs(float(so_tien)):,}đ cho {ma_nv} (mã {ma_luong}) - refund {ma_gd_refund}",
            nguoi_thuc_hien=username,
            ip=ip,
            device=device,
            scope="REFUND"
        )

        ghi_lich_su(
            ten_bang="Luong",
            ma_ban_ghi=ma_luong,
            hanh_dong="Hoàn tiền lương",
            gia_tri_moi=f"Chuyển về trạng thái chưa thanh toán (refund {ma_gd_refund})",
            nguoi_thuc_hien=username,
            ip=ip,
            device=device,
            scope="REFUND_STATE"
        )

        conn.commit()

        print(f"[REFUND] ✅ Hoàn tiền thành công cho {ma_nv} | Mã hoàn: {ma_gd_refund}")

        return jsonify({
            "success": True,
            "message": "Hoàn tiền giả lập thành công.",
            "refund_id": ma_gd_refund,
            "pdf": pdf_path
        })

    except Exception as e:
        conn.rollback()
        print("[ERROR] ❌ refund_transaction:", e)
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "message": f"Lỗi khi hoàn tiền: {e}"}), 500

    finally:
        cursor.close()
        conn.close()
