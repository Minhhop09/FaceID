from datetime import datetime, timedelta, date, time

# ============================================================
# 🕓 CHUYỂN GIỜ DÙNG CHO TÍNH TOÁN
# ============================================================
def to_datetime(val):
    """Chuyển string/time/datetime về datetime hợp lệ."""
    if isinstance(val, datetime): 
        return val
    if isinstance(val, time): 
        return datetime.combine(date.today(), val)
    if isinstance(val, str):
        val = val.split('.')[0].strip()
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(val, fmt)
            except:
                pass
    return None
# ============================================================
# 💵 ĐỌC THAM SỐ LƯƠNG (TỐI ƯU + AN TOÀN)
# ============================================================
def get_tham_so_luong(cursor):
    """
    Đọc toàn bộ tham số từ bảng ThamSoLuong và trả về dict
    Ví dụ: {'PhuCapAnTrua': 30000.0, 'PIT_ThueThuNhap': 0.05, ...}
    """
    params = {}
    try:
        cursor.execute("SELECT TenThamSo, GiaTri FROM ThamSoLuong")
        rows = cursor.fetchall()
        for name, value in rows:
            if value is None:
                continue
            try:
                params[name] = float(value)
            except (ValueError, TypeError):
                params[name] = value
        return params
    except Exception as e:
        print(f"[ERROR] ❌ Không thể đọc bảng ThamSoLuong: {e}")
        return {}
# ============================================================
# 💰 TÍNH LƯƠNG NHÂN VIÊN (3 CA/NGÀY × 4 GIỜ, DÙNG LƯƠNG GIỜ CƠ BẢN)
# ============================================================
# ============================================================
# 🧮 HÀM CHÍNH: TÍNH LƯƠNG NHÂN VIÊN
# ============================================================
def tinh_luong_nv(cursor, ma_nv, thangnam, nguoi_tinh, save_to_db=True, return_detail=False):
    """
    ✅ Tính lương nhân viên theo 3 ca/ngày:
      - 1 ca = 4 tiếng (sáng / chiều / tối)
      - < 4h → tính theo giờ (LuongGioCoBan × giờ × hệ số)
      - ≥ 4h → tính trọn ca (500k ca ngày, 800k ca tối)
      - > 4h → cộng thêm tăng ca (theo giờ × hệ số tăng ca)
      - Có phạt đi trễ, phụ cấp, PIT, lưu DB
    """

    # === 0️⃣ Lấy tham số hệ thống ===
    params = get_tham_so_luong(cursor)
    current_month = thangnam.month
    current_year = thangnam.year

    # === 1️⃣ Lấy thông tin nhân viên ===
    cursor.execute("SELECT HoTen, ChucVu, LuongGioCoBan FROM NhanVien WHERE MaNV=?", (ma_nv,))
    row = cursor.fetchone()
    if not row:
        return (0, 0, []) if return_detail else (0, 0)

    ho_ten, chucvu, luong_gio_cb = row
    chucvu = (chucvu or "").lower()

    # 🧾 Ép kiểu lương giờ cơ bản sang float
    try:
        if luong_gio_cb is None:
            luong_gio_cb = 100_000.0
        elif isinstance(luong_gio_cb, Decimal):
            luong_gio_cb = float(luong_gio_cb)
        else:
            luong_gio_cb = float(luong_gio_cb)
    except Exception as e:
        print(f"[WARN] ⚠️ Không ép được LuongGioCoBan cho {ma_nv}: {e}")
        luong_gio_cb = 100_000.0

    # === 2️⃣ Hệ số chức vụ ===
    if "hr" in chucvu or "nhân sự" in chucvu:
        he_so_cv = 2.2
    elif "trưởng phòng" in chucvu:
        he_so_cv = 2.0
    elif "phó phòng" in chucvu:
        he_so_cv = 1.5
    elif "thực tập" in chucvu:
        he_so_cv = 0.8
    elif "thử việc" in chucvu:
        he_so_cv = params.get("PhanTramLuongThuViec", 0.85)
    else:
        he_so_cv = 1.0

    # === 3️⃣ Dữ liệu chấm công ===
    cursor.execute("""
        SELECT 
            CC.MaCa, CC.NgayChamCong, CC.GioVao, CC.GioRa,
            CLV.GioBatDau, CLV.GioKetThuc, CLV.TenCa
        FROM ChamCong CC
        LEFT JOIN CaLamViec CLV ON CC.MaCa = CLV.MaCa
        WHERE CC.MaNV = ?
          AND MONTH(CC.NgayChamCong) = ?
          AND YEAR(CC.NgayChamCong) = ?
          AND (CC.DaXoa IS NULL OR CC.DaXoa IN (0, 1))
        ORDER BY CC.NgayChamCong, CC.MaCa
    """, (ma_nv, current_month, current_year))
    cham_cong_records = cursor.fetchall()
    print(f"[DEBUG] 📅 {ma_nv} có {len(cham_cong_records)} bản ghi chấm công.")

    if not cham_cong_records:
        return (0, 0, []) if return_detail else (0, 0)

    tong_gio, tong_tien = 0.0, 0.0
    chi_tiet_ca = []

    # === 4️⃣ Xử lý từng ca ===
    for ma_ca, ngay, gio_vao_raw, gio_ra_raw, gio_bd, gio_kt, ten_ca in cham_cong_records:
        if not gio_vao_raw or not gio_ra_raw:
            chi_tiet_ca.append({
                "NgayChamCong": ngay.strftime("%d/%m/%Y"),
                "Ca": ten_ca or ma_ca,
                "GioVao": "—",
                "GioRa": "—",
                "SoGio": 0,
                "HeSo": he_so_cv,
                "Tien": 0,
                "LyDoTru": "⚠️ Chưa có giờ vào/ra",
                "CongThuc": ""
            })
            continue

        # ✅ Ghép giờ
        gio_vao = datetime.combine(ngay, gio_vao_raw.time())
        gio_ra = datetime.combine(ngay, gio_ra_raw.time())
        if gio_ra < gio_vao:
            gio_ra += timedelta(days=1)

        so_gio = round((gio_ra - gio_vao).total_seconds() / 3600, 2)
        tong_gio += so_gio

        # 🕒 Đi trễ
        gio_bd_dt = datetime.combine(ngay, gio_bd or time(8, 0))
        di_tre = max((gio_vao - gio_bd_dt).total_seconds() / 60, 0)
        cuoi_tuan = ngay.weekday() >= 5
        he_so_tang_ca = params.get("HeSoTangCaNgayThuong", 1.5 if not cuoi_tuan else 2.0)

        # 💸 Phạt đi trễ
        phat = 0
        if di_tre <= 5:
            ly_do = "Đúng giờ"
        elif di_tre <= 30:
            phat = params.get("PhatTre30", 50_000)
            ly_do = f"Trễ {int(di_tre)} phút (phạt 50k)"
        elif di_tre <= 60:
            phat = params.get("PhatTre60", 100_000)
            ly_do = f"Trễ {int(di_tre)} phút (phạt 100k)"
        else:
            phat = params.get("PhatTre120", 200_000)
            ly_do = f"Trễ {int(di_tre)} phút (phạt 200k)"

        # 💰 Tính lương theo ca
        LUONG_CA_NGAY = 500_000
        LUONG_CA_TOI = 800_000
        la_ca_toi = any(x in (ten_ca or "").lower() for x in ["tối", "đêm", "ca 3"])
        muc_ca_nv = LUONG_CA_TOI if la_ca_toi else LUONG_CA_NGAY

        note_them = ""
        if so_gio < 4:
            # Chưa đủ ca → tính theo giờ
            luong_tam = so_gio * luong_gio_cb * he_so_cv
            note_them = f"; chưa đủ 4h → {so_gio}h × {luong_gio_cb:,}"
        else:
            # Đủ ca → tính trọn ca
            luong_tam = muc_ca_nv * he_so_cv
            # Nếu làm hơn 4h → tăng ca
            if so_gio > 4:
                gio_tang_ca = round(so_gio - 4, 2)
                luong_tam += gio_tang_ca * luong_gio_cb * he_so_cv * he_so_tang_ca
                note_them = f"; tăng ca {gio_tang_ca}h"

        # Tổng tiền sau phạt
        tien = luong_tam - phat
        tong_tien += tien
        ly_do += note_them

        if return_detail:
            chi_tiet_ca.append({
                "NgayChamCong": ngay.strftime("%d/%m/%Y"),
                "Ca": ten_ca or ma_ca,
                "GioVao": gio_vao.strftime("%H:%M"),
                "GioRa": gio_ra.strftime("%H:%M"),
                "SoGio": so_gio,
                "HeSo": he_so_cv,
                "Tien": round(tien, 0),
                "LyDoTru": ly_do,
                "CongThuc": f"{'Ca tối' if la_ca_toi else 'Ca ngày'}: {muc_ca_nv:,} × {he_so_cv} {note_them} − {phat:,}"
            })

    # === 5️⃣ Phụ cấp + Thuế ===
    phu_cap_xang = params.get("PhuCapXangXe", 500_000)
    phu_cap_an = params.get("PhuCapAnTrua", 30_000) * len(cham_cong_records)
    phu_cap_khac = params.get("PhuCapKhac", 200_000)
    phu_cap = phu_cap_xang + phu_cap_an + phu_cap_khac

    pit = tong_tien * params.get("PIT_ThueThuNhap", 0.05)
    tong_tien_thuc = tong_tien + phu_cap - pit

    # === 6️⃣ Lưu DB ===
    if save_to_db:
        thang_nam_date = thangnam.replace(day=1)
        cursor.execute("DELETE FROM Luong WHERE MaNV=? AND ThangNam=?", (ma_nv, thang_nam_date))
        cursor.execute("""
            INSERT INTO Luong (MaNV, ThangNam, SoGioLam, TongTien, TrangThai, NguoiTinhLuong, NgayTinhLuong, DaXoa)
            VALUES (?, ?, ?, ?, 1, ?, GETDATE(), 1)
        """, (ma_nv, thang_nam_date, tong_gio, tong_tien_thuc, nguoi_tinh))

    # === 7️⃣ Debug tổng kết ===
    print(f"[DEBUG] 💰 {ma_nv} | Tổng giờ: {tong_gio:.2f}h | Tổng tiền: {tong_tien_thuc:,.0f}đ")

    # === 8️⃣ Trả kết quả ===
    return (
        round(tong_gio, 2),
        round(tong_tien_thuc, 0),
        chi_tiet_ca
    ) if return_detail else (round(tong_gio, 2), round(tong_tien_thuc, 0))