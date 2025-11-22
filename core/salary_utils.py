from datetime import datetime, timedelta, date, time
from decimal import Decimal, ROUND_HALF_UP


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
# 💵 HÀM: get_tham_so_luong(cursor)
# ============================================================
def get_tham_so_luong(cursor):
    """
    Đọc tham số lương từ DB, nếu thiếu thì dùng bộ mặc định.
    """
    params = {}
    try:
        cursor.execute("SELECT TenThamSo, GiaTri FROM ThamSoLuong WHERE GiaTri IS NOT NULL")
        rows = cursor.fetchall()
        for name, value in rows:
            name = name.strip()
            try:
                params[name] = float(value)
            except (ValueError, TypeError):
                params[name] = value
    except Exception as e:
        print(f"[ERROR] ❌ Không thể đọc bảng ThamSoLuong: {e}")

    # Bộ mặc định — chỉ thêm nếu DB chưa có
    defaults = {
        "HeSo_TruongPhong": 1.5,
        "HeSo_PhoPhong": 1.3,
        "HeSo_HR": 2.2,
        "HeSo_NhanVien": 1.0,
        "HeSo_ThuViec": 0.85,
        "HeSo_ThucTap": 0.8,

        "HeSoOT_NgayThuong": 1.5,
        "HeSoOT_Thu7": 1.3,
        "HeSoOT_ChuNhat": 1.5,
        "HeSoOT_Lenh": 3.0,

        "HeSoCaNgay": 1.0,
        "HeSoCaToi": 1.3,
        "HeSoCaDem": 1.5,

        "PhuCapAnTrua": 30_000,
        "PhuCapXangXe": 500_000,
        "PhuCapKhac": 200_000,
        "ThuongChuyenCan": 300_000,

        "PhatTre30": 50_000,
        "PhatTre60": 100_000,
        "PhatTre120": 200_000,
        "KhauTru_BHXH": 0.08,
        "KhauTru_BHYT": 0.015,
        "KhauTru_BHTN": 0.01,
        "PIT_ThueThuNhap": 0.05,

        "SoPhepNamMacDinh": 18,
        "SoCaPhepNamMacDinh": 36,
        "SoCaTrongNgay": 3,
        "SoCaTinhLuong1Ngay": 2,

        "LuongCoBanMacDinh": 15_000_000,
        "LuongGioCoBan": 100_000,
    }

    # Chỉ thêm mặc định nếu DB chưa có
    for k, v in defaults.items():
        params.setdefault(k, v)

    return params

# ============================================================
# 🔢 HỖ TRỢ SINH MÃ CHI TIẾT
# ============================================================
def next_ma_ct_luong(cursor, ma_luong):
    cursor.execute("SELECT COUNT(*) FROM ChiTietLuong WITH (UPDLOCK) WHERE MaLuong = ?", (ma_luong,))
    count = cursor.fetchone()[0] or 0
    return f"{ma_luong}_{count + 1}"


from datetime import datetime, timedelta, date, time
from decimal import Decimal, ROUND_HALF_UP

# ============================================================
# 🧾 HÀM GHI LỊCH SỬ THAY ĐỔI (dùng chung)
# ============================================================
def ghi_lich_su_thay_doi(cursor, ten_bang, ma_ban_ghi, hanh_dong,
                          truong_thay_doi=None, gia_tri_cu=None, gia_tri_moi=None,
                          nguoi_thuc_hien="Hệ thống", ip=None, device=None, scope=None):
    """
    ✅ Ghi log vào bảng LichSuThayDoi
    """
    try:
        cursor.execute("""
            INSERT INTO LichSuThayDoi (
                TenBang, MaBanGhi, HanhDong, TruongThayDoi,
                GiaTriCu, GiaTriMoi, ThoiGian, NguoiThucHien,
                IPAddress, DeviceID, Scope
            )
            VALUES (?, ?, ?, ?, ?, ?, GETDATE(), ?, ?, ?, ?)
        """, (
            ten_bang, ma_ban_ghi, hanh_dong, truong_thay_doi or "Toàn bộ",
            str(gia_tri_cu or ""), str(gia_tri_moi or ""),
            nguoi_thuc_hien, str(ip or "Unknown"), str(device or "Unknown"), str(scope or "")
        ))
        cursor.connection.commit()
        print(f"[LOG] 📝 {hanh_dong} → {ten_bang}.{ma_ban_ghi}")
    except Exception as e:
        print(f"[WARN] Không thể ghi log LichSuThayDoi: {e}")

# ============================================================
# 💰 HÀM TÍNH LƯƠNG NHÂN VIÊN — FINAL FIXED V18 (FaceID Payroll)
# ============================================================
def tinh_luong_nv(cursor, ma_nv, thangnam, nguoi_tinh, save_to_db=True, return_detail=False,
                  ip_addr="AutoCalc", device_name="salary_utils.py"):
    """
    ✅ FINAL FIXED V18 — Chuẩn phụ cấp + thưởng chuyên cần
    ------------------------------------------------------------
    ✔ Lấy dữ liệu gốc từ LichLamViec (đảm bảo đủ ca đã qua)
    ✔ Bỏ ca tương lai (LLV.NgayLam <= GETDATE())
    ✔ Nghỉ phép có lương giảm 1 ca phép, không cộng đôi
    ✔ Phụ cấp ăn trưa chỉ tính cho ca có đi làm (1, 2)
    ✔ Thưởng chuyên cần chỉ khi không vắng & ≥95% ca làm
    ✔ Gross = Lương chính + Phụ cấp
    ✔ Net = Gross - BH - PIT
    ------------------------------------------------------------
    """
    from datetime import datetime, timedelta, time
    from decimal import Decimal, ROUND_HALF_UP

    params = get_tham_so_luong(cursor)
    current_month, current_year = thangnam.month, thangnam.year

    # === 1️⃣ Thông tin nhân viên ===
    cursor.execute("""
        SELECT HoTen, ChucVu, LuongGioCoBan, SoCaPhepConLai
        FROM NhanVien WHERE MaNV = ?
    """, (ma_nv,))
    row = cursor.fetchone()
    if not row:
        return (0, 0, []) if return_detail else (0, 0)

    ho_ten, chucvu, luong_gio_cb, so_ca_phep_con = row
    chucvu = (chucvu or "").lower()
    so_ca_phep_con = int(so_ca_phep_con or 0)
    luong_gio_cb = Decimal(str(luong_gio_cb or params["LuongGioCoBan"]))
    def dec_param(k, d): return Decimal(str(params.get(k, d)))

    # === 2️⃣ Hệ số chức vụ ===
    if "trưởng phòng" in chucvu:
        he_so_cv = dec_param("HeSo_TruongPhong", 1.5)
    elif "phó phòng" in chucvu:
        he_so_cv = dec_param("HeSo_PhoPhong", 1.3)
    elif "hr" in chucvu or "nhân sự" in chucvu:
        he_so_cv = dec_param("HeSo_HR", 2.2)
    elif "thử việc" in chucvu:
        he_so_cv = dec_param("HeSo_ThuViec", 0.85)
    elif "thực tập" in chucvu:
        he_so_cv = dec_param("HeSo_ThucTap", 0.8)
    else:
        he_so_cv = dec_param("HeSo_NhanVien", 1.0)

    # === 3️⃣ Dữ liệu ca làm việc (chỉ lấy ca đã qua) ===
    cursor.execute("""
        SELECT 
            LLV.MaCa,
            LLV.NgayLam,
            CC.GioVao, CC.GioRa,
            CLV.GioBatDau, CLV.GioKetThuc, CLV.TenCa,
            CLV.HeSo,
            ISNULL(CC.CoDon, 0) AS CoDon,
            ISNULL(CC.TrangThai, LLV.TrangThai) AS TrangThai
        FROM LichLamViec LLV
        LEFT JOIN CaLamViec CLV ON LLV.MaCa = CLV.MaCa
        LEFT JOIN ChamCong CC 
            ON LLV.MaNV = CC.MaNV 
            AND LLV.MaCa = CC.MaCa 
            AND LLV.NgayLam = CC.NgayChamCong
        WHERE LLV.MaNV = ?
          AND MONTH(LLV.NgayLam) = ?
          AND YEAR(LLV.NgayLam) = ?
          AND LLV.NgayLam <= CAST(GETDATE() AS date)
          AND (LLV.DaXoa IS NULL OR LLV.DaXoa = 1)
        ORDER BY LLV.NgayLam, LLV.MaCa
    """, (ma_nv, current_month, current_year))
    cham_cong_list = cursor.fetchall()
    if not cham_cong_list:
        return (0, 0, []) if return_detail else (0, 0)

    tong_gio = Decimal('0')
    tong_tien = Decimal('0')
    tong_phat = Decimal('0')
    chi_tiet_ca = []

    # === 4️⃣ Duyệt từng ca ===
    for ma_ca, ngay, gio_vao_raw, gio_ra_raw, gio_bd, gio_kt, ten_ca, he_so, co_don, trang_thai in cham_cong_list:
        he_so_ca = Decimal(str(he_so or 1.0))
        ghi_chu = ""
        phat = Decimal('0')
        tien = Decimal('0')
        so_gio_tinh = Decimal('0')

        # --- Nghỉ phép ---
        if trang_thai == 3:  # Nghỉ phép có lương
            if so_ca_phep_con > 0:
                so_gio_tinh = Decimal('4')
                tien = so_gio_tinh * luong_gio_cb * he_so_cv * he_so_ca
                tong_gio += so_gio_tinh
                so_ca_phep_con -= 1
                ghi_chu = f"Nghỉ phép có lương (4h, trừ 1 ca, còn {so_ca_phep_con})"
            else:
                ghi_chu = "Hết phép (không tính lương)"

        elif trang_thai == 4:  # Có đơn nhưng không lương
            ghi_chu = "Nghỉ có đơn (không tính lương)"

        elif trang_thai == 0:  # Vắng không phép
            tien = -(luong_gio_cb * Decimal('4') * he_so_cv * he_so_ca)
            ghi_chu = "Vắng không phép (trừ 1 ca)"

        else:
            # --- Ca làm bình thường ---
            if not gio_vao_raw or not gio_ra_raw:
                ghi_chu = "⚠️ Thiếu giờ vào/ra"
            else:
                gio_vao = datetime.combine(ngay, gio_vao_raw.time())
                gio_ra = datetime.combine(ngay, gio_ra_raw.time())
                if gio_ra < gio_vao:
                    gio_ra += timedelta(days=1)
                so_gio_tinh = Decimal(str(round((gio_ra - gio_vao).total_seconds() / 3600, 2)))
                tong_gio += so_gio_tinh

                # --- Phạt đi muộn ---
                gio_bd_dt = datetime.combine(ngay, gio_bd or time(8, 0))
                di_tre = max((gio_vao - gio_bd_dt).total_seconds() / 60, 0)
                if di_tre <= 15:
                    ghi_chu = "Đúng giờ hoặc trễ ≤15p"
                elif di_tre <= 60:
                    phat = dec_param("PhatTre60", 100_000)
                    ghi_chu = f"Trễ {int(di_tre)}p (phạt {int(phat):,}đ)"
                elif di_tre <= 120:
                    phat = dec_param("PhatTre120", 200_000)
                    ghi_chu = f"Trễ {int(di_tre)}p (phạt {int(phat):,}đ)"
                else:
                    phat = dec_param("PhatTre120", 200_000)
                    ghi_chu = f"Trễ {int(di_tre)}p (>120p, phạt {int(phat):,}đ)"
                tong_phat += phat

                # --- Hệ số Thứ 7 / CN ---
                weekday = ngay.weekday()
                if weekday == 5:
                    he_so_ca *= dec_param("HeSoOT_Thu7", 1.3)
                    ghi_chu += " | Thứ 7 (+30%)"
                elif weekday == 6:
                    he_so_ca *= dec_param("HeSoOT_ChuNhat", 1.5)
                    ghi_chu += " | CN (+50%)"

                # --- Tính OT ---
                gio_chuan = Decimal('4')
                if so_gio_tinh > gio_chuan:
                    gio_ot = so_gio_tinh - gio_chuan
                    he_so_ot = dec_param("HeSoOT_NgayThuong", 1.5)
                    tien = (gio_chuan * luong_gio_cb * he_so_cv * he_so_ca) + \
                           (gio_ot * luong_gio_cb * he_so_cv * he_so_ca * he_so_ot)
                    ghi_chu += f" | OT {float(gio_ot)}h"
                else:
                    tien = so_gio_tinh * luong_gio_cb * he_so_cv * he_so_ca

                tien -= phat

        tong_tien += tien

        if return_detail:
            chi_tiet_ca.append({
                "NgayChamCong": ngay.strftime("%d/%m/%Y"),
                "Ca": ten_ca or ma_ca,
                "GioVao": gio_vao_raw.strftime("%H:%M") if gio_vao_raw else "—",
                "GioRa": gio_ra_raw.strftime("%H:%M") if gio_ra_raw else "—",
                "SoGio": float(so_gio_tinh),
                "Tien": float(tien),
                "Phat": float(phat),
                "TrangThai": trang_thai,
                "GhiChu": ghi_chu
            })

    # === 5️⃣ Phụ cấp & Thưởng ===
    so_ca_di_lam = sum(1 for r in cham_cong_list if r[9] in (1, 2))
    so_ca_vang = sum(1 for r in cham_cong_list if r[9] == 0)
    tong_ca = len(cham_cong_list)

    if so_ca_di_lam == 0:
        phu_cap_xang = phu_cap_an = phu_cap_khac = thuong_chuyen_can = Decimal('0')
    else:
        phu_cap_xang = dec_param("PhuCapXangXe", 500_000)
        phu_cap_an = dec_param("PhuCapAnTrua", 30_000) * Decimal(so_ca_di_lam)
        phu_cap_khac = dec_param("PhuCapKhac", 200_000)
        ty_le_chuyen_can = so_ca_di_lam / tong_ca if tong_ca else 0
        thuong_chuyen_can = dec_param("ThuongChuyenCan", 300_000) if (so_ca_vang == 0 and ty_le_chuyen_can >= 0.95) else Decimal('0')

    tong_phu_cap = phu_cap_xang + phu_cap_an + phu_cap_khac + thuong_chuyen_can

    # === 6️⃣ Khấu trừ & Thuế ===
    def calculate_pit(income):
        if income <= 0: return Decimal('0')
        brackets = [(5_000_000, 0.05), (5_000_000, 0.10), (8_000_000, 0.15),
                    (14_000_000, 0.20), (20_000_000, 0.25), (28_000_000, 0.30), (float('inf'), 0.35)]
        tax = 0
        for limit, rate in brackets:
            if income <= 0: break
            taxable = min(income, limit)
            tax += taxable * rate
            income -= taxable
        return Decimal(tax).quantize(Decimal('1.'), rounding=ROUND_HALF_UP)

    luong_chinh = tong_tien.quantize(Decimal('1.'), rounding=ROUND_HALF_UP)
    gross = (luong_chinh + tong_phu_cap).quantize(Decimal('1.'), rounding=ROUND_HALF_UP)
    tong_khau_tru_bh = dec_param("KhauTru_BHXH", 0.08) + dec_param("KhauTru_BHYT", 0.015) + dec_param("KhauTru_BHTN", 0.01)
    bao_hiem = (gross * tong_khau_tru_bh).quantize(Decimal('1.'), rounding=ROUND_HALF_UP)
    tnct = float(gross - bao_hiem - Decimal('11000000'))
    pit = calculate_pit(tnct if tnct > 0 else 0)
    net = (gross - bao_hiem - pit).quantize(Decimal('1.'), rounding=ROUND_HALF_UP)

    # === 7️⃣ Ghi DB + Log ===
    ma_luong = f"L{ma_nv}_{current_year}{current_month:02d}"
    if save_to_db:
        cursor.execute("DELETE FROM ChiTietLuong WHERE MaLuong = ?", (ma_luong,))
        cursor.execute("DELETE FROM Luong WHERE MaLuong=? OR (MaNV=? AND YEAR(ThangNam)=? AND MONTH(ThangNam)=?)",
                       (ma_luong, ma_nv, current_year, current_month))
        cursor.execute("""
            INSERT INTO Luong (MaLuong, MaNV, ThangNam, SoGioLam, TongTien, LuongGross, LuongNet, TrangThai,
                               NguoiTinhLuong, NgayTinhLuong, DaXoa)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, GETDATE(), 1)
        """, (ma_luong, ma_nv, thangnam.replace(day=1),
              float(tong_gio), float(luong_chinh), float(gross), float(net), nguoi_tinh))

        def add_ct(loai, so_tien, note=""):
            cursor.execute("""
                INSERT INTO ChiTietLuong (MaCTLuong, MaLuong, MaNV, LoaiKhoan, SoTien, GhiChu, NgayTinh)
                VALUES (?, ?, ?, ?, ?, ?, GETDATE())
            """, (
                next_ma_ct_luong(cursor, ma_luong),
                ma_luong, ma_nv, loai, float(so_tien), note
            ))
        add_ct("Lương chính", luong_chinh, "Tổng tiền chấm công")
        add_ct("Phụ cấp & thưởng", tong_phu_cap)
        add_ct("Khấu trừ BHXH+BHYT+BHTN", -bao_hiem)
        add_ct("Thuế TNCN", -pit)
        add_ct("Lương Net", net)
        cursor.connection.commit()

        ghi_lich_su_thay_doi(cursor, "Luong", ma_luong,
            "Tính lương nhân viên",
            gia_tri_moi=f"Tính lương {ma_nv} {current_month:02d}/{current_year}, Net={float(net):,.0f}đ",
            nguoi_thuc_hien=nguoi_tinh, ip=ip_addr, device=device_name, scope="Luong_TinhLuong")

    print(f"[DEBUG] 💰 {ma_nv}: Lương chính={luong_chinh:,.0f} | Gross={gross:,.0f} | Net={net:,.0f}")

    # === 8️⃣ Trả kết quả ===
    if return_detail:
        return (float(tong_gio), float(net), chi_tiet_ca, float(luong_chinh), float(gross))
    else:
        return (float(tong_gio), float(net))
