# ============================================================
# 💰 Payment Utilities - FaceID System
# ============================================================
import random
import string
import time
import os
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta
# ============================================================
# 🧾 PDF Biên Lai Thanh Toán Lương (Premium – màu xanh, QR, mã vạch)
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, Image, Flowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics   # ✅ THÊM DÒNG NÀY
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing


# ============================================================
# 📦 Mã giao dịch & phí thanh toán
# ============================================================
def generate_txid(prefix="TX"):
    """Sinh mã giao dịch ngẫu nhiên."""
    return prefix + ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))


def calc_fee(method: str, amount: Decimal) -> Decimal:
    """Tính phí giao dịch theo phương thức thanh toán."""
    method = (method or "").lower()

    if method == "cash":
        return Decimal("0")

    if method == "bank":
        # ví dụ: 0.1% + 3,300đ
        fee = (amount * Decimal("0.001")).quantize(Decimal("1."), rounding=ROUND_HALF_UP) + Decimal("3300")
        return fee

    if method in ("momo", "zalopay"):
        # ví dụ: 0.8% (min 2,000đ)
        fee = (amount * Decimal("0.008")).quantize(Decimal("1."), rounding=ROUND_HALF_UP)
        return fee if fee >= Decimal("2000") else Decimal("2000")

    return Decimal("0")


# ============================================================
# 🧪 Fake Payment Gateway
# ============================================================
def fake_payment_gateway(method: str, amount: Decimal):
    """
    Mô phỏng cổng thanh toán thật.
    - Delay 1 giây
    - Xác suất thành công 98%
    """
    time.sleep(1.0)
    if random.random() < 0.98:
        return {"success": True, "txid": generate_txid()}
    return {"success": False, "error": "Fake gateway failure"}


def fake_gateway_charge(method: str, amount: Decimal, account=None, bank=None):
    """
    Mô phỏng gọi cổng thanh toán chi tiết.
    - delay 0.8–1.6s
    - xác suất thành công ~97%
    """
    time.sleep(random.uniform(0.8, 1.6))
    success = random.random() < 0.97
    txid = generate_txid(method.upper()[:3] or "TX")
    message = "Thanh toán thành công." if success else "Giao dịch bị từ chối."
    return {"success": success, "txid": txid, "message": message}


# ============================================================
# 🧾 Chuẩn hóa tài khoản
# ============================================================
def normalize_account(phuong_thuc: str, so_tk: str, ngan_hang: str):
    """
    Chuẩn hóa/kiểm tra thông tin tài khoản theo phương thức:
    - bank: cần số TK + tên NH
    - momo/zalopay: cho phép số ĐT (10-11 số)
    - cash: không bắt buộc
    """
    p = (phuong_thuc or "").lower()

    if p == "bank":
        if not so_tk or not ngan_hang:
            raise ValueError("Thiếu số tài khoản hoặc tên ngân hàng.")
        return so_tk.strip(), ngan_hang.strip()

    if p in ("momo", "zalopay"):
        if not so_tk or not so_tk.strip().isdigit() or len(so_tk.strip()) not in (10, 11):
            raise ValueError("Ví điện tử yêu cầu số điện thoại 10–11 số.")
        return so_tk.strip(), p.upper()

    return None, None  # cash


# ============================================================
# 🔐 OTP Helpers
# ============================================================
def generate_otp(length=6):
    """Sinh mã OTP ngẫu nhiên."""
    return ''.join(random.choices(string.digits, k=length))


def otp_expires_at(minutes=5):
    """Thời gian hết hạn OTP."""
    return datetime.utcnow() + timedelta(minutes=minutes)



FONT_PATH = os.path.join(os.getcwd(), "static", "fonts", "DejaVuSans.ttf")
if os.path.exists(FONT_PATH):
    pdfmetrics.registerFont(TTFont("DejaVu", FONT_PATH))
else:
    print("[⚠️] Không tìm thấy font DejaVuSans.ttf — tiếng Việt có thể lỗi.")


def _draw_watermark(c, doc):
    c.saveState()
    c.setFillColorRGB(0.85, 0.85, 0.85)
    if hasattr(c, "setFillAlpha"):
        c.setFillAlpha(0.15)
    c.translate(doc.width / 2 + doc.leftMargin, doc.height / 2 + doc.bottomMargin)
    c.rotate(30)
    c.setFont("DejaVu", 38)
    c.drawCentredString(0, 0, "FaceID System")
    c.restoreState()


class BarcodeFlowable(Flowable):
    def __init__(self, value, width=80*mm, height=18*mm):
        super().__init__()
        self.value = value
        self.width = width
        self.height = height

    def wrap(self, availW, availH):
        return self.width, self.height

    def draw(self):
        code = code128.Code128(self.value, barHeight=self.height * 0.8, humanReadable=True)
        code.drawOn(self.canv, 0, 0)


# --- IMPORTS (nếu chưa có ở đầu file, đảm bảo có những import sau)
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.platypus import Flowable
from reportlab.pdfbase.ttfonts import TTFont
import json
import csv
try:
    import pyodbc
except Exception:
    pyodbc = None  # nếu chưa cài pyodbc, hàm lưu DB sẽ báo lỗi rõ ràng

# --- Đảm bảo font đã đăng ký (nếu chưa)
FONT_PATH = os.path.join(os.getcwd(), "static", "fonts", "DejaVuSans.ttf")
if os.path.exists(FONT_PATH):
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", FONT_PATH))
    except Exception:
        pass

# --- Barcode Flowable giữ nguyên
class BarcodeFlowable(Flowable):
    def __init__(self, value, width=140*mm, height=22*mm):
        super().__init__()
        self.value = value
        self.width = width
        self.height = height

    def wrap(self, availW, availH):
        return self.width, self.height

    def draw(self):
        # Vẽ Code128 lớn hơn để giống hoá đơn ngân hàng
        barcode = code128.Code128(self.value, barHeight=self.height * 0.9, humanReadable=True)
        # căn giữa: dịch canvas tới giữa available width
        x = (self.width - barcode.width) / 2 if hasattr(barcode, "width") else 0
        barcode.drawOn(self.canv, x, 0)


# --- Hàm lưu record: (1) lưu DB bằng pyodbc (nếu có), (2) fallback CSV
def save_payment_record_db(conn_str, txid, ma_nv, so_tk, ngan_hang, phuong_thuc, amount, fee, ngay):
    """
    Lưu vào SQL Server (yêu cầu pyodbc và chuỗi kết nối conn_str).
    Tạo sẵn bảng GiaoDichLuong nếu chưa có:
    CREATE TABLE GiaoDichLuong (
        MaGD NVARCHAR(50) PRIMARY KEY,
        MaNV NVARCHAR(50),
        SoTien DECIMAL(18,2),
        Phi DECIMAL(18,2),
        PhuongThuc NVARCHAR(50),
        SoTK NVARCHAR(100),
        NganHang NVARCHAR(200),
        ThoiGian DATETIME
    );
    """
    if pyodbc is None:
        raise RuntimeError("pyodbc không được cài. Cài bằng 'pip install pyodbc' nếu muốn lưu vào SQL Server.")
    conn = pyodbc.connect(conn_str)
    cur = conn.cursor()
    cur.execute("""
        IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = 'GiaoDichLuong')
        BEGIN
            CREATE TABLE GiaoDichLuong (
                MaGD NVARCHAR(50) PRIMARY KEY,
                MaNV NVARCHAR(50),
                SoTien DECIMAL(18,2),
                Phi DECIMAL(18,2),
                PhuongThuc NVARCHAR(50),
                SoTK NVARCHAR(100),
                NganHang NVARCHAR(200),
                ThoiGian DATETIME
            )
        END
    """)
    conn.commit()
    cur.execute("""
        INSERT INTO GiaoDichLuong (MaGD, MaNV, SoTien, Phi, PhuongThuc, SoTK, NganHang, ThoiGian)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (txid, ma_nv, float(amount), float(fee), phuong_thuc, so_tk or "", ngan_hang or "", ngay))
    conn.commit()
    cur.close()
    conn.close()
    return True


def save_payment_record_csv(csv_path, txid, ma_nv, so_tk, ngan_hang, phuong_thuc, amount, fee, ngay):
    """Lưu fallback vào CSV (append)."""
    header = ["MaGD", "MaNV", "SoTK", "NganHang", "PhuongThuc", "SoTien", "Phi", "ThoiGian"]
    exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline='', encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(header)
        w.writerow([txid, ma_nv, so_tk or "", ngan_hang or "", phuong_thuc, float(amount), float(fee), ngay.isoformat()])
    return csv_path

# ============================================================
# 🧾 Hàm tạo biên lai thanh toán lương (Premium)
# ============================================================
def generate_salary_pdf(txid, ma_nv, ho_ten, so_tien, phuong_thuc, phi,
                        file_path=None, signature_img_path=None, qr_target=None,
                        so_tk=None, ngan_hang=None):
    """
    Tạo biên lai premium:
    - Mã vạch ở đầu (giống biên lai ngân hàng)
    - Hiển thị Số tài khoản, Ngân hàng, Phương thức
    - Tự động lưu CSV trong /receipts/payments_log.csv
    """

    # ------------------------------------------------------------
    # ⚙️ Chuẩn bị file
    # ------------------------------------------------------------
    if not file_path:
        file_path = os.path.join("receipts", f"receipt_{txid}.pdf")

    doc = SimpleDocTemplate(
        file_path,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=35,
        bottomMargin=30,
        title=f"Biên lai {txid}"
    )

    # ------------------------------------------------------------
    # 🧱 Style chữ
    # ------------------------------------------------------------
    styles = getSampleStyleSheet()
    title_font = "DejaVu" if "DejaVu" in pdfmetrics.getRegisteredFontNames() else "Helvetica"

    style_title = ParagraphStyle(
        "Title",
        parent=styles["Heading1"],
        alignment=1,
        fontName=title_font,
        fontSize=16,
        leading=22,
        textColor=colors.white
    )
    style_body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontName=title_font,
        fontSize=12,
        leading=18
    )
    style_footer = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        alignment=1,
        fontName=title_font,
        fontSize=10,
        leading=14,
        textColor=colors.grey
    )

    elements = []

    # ------------------------------------------------------------
    # 🧾 MÃ VẠCH Ở TRÊN CÙNG
    # ------------------------------------------------------------
    stk_for_code = so_tk if so_tk else ""
    bank_for_code = ngan_hang if ngan_hang else ""
    code_value = f"{txid}|{ma_nv}|{stk_for_code}|{bank_for_code}|{int(so_tien)}"
    barcode_flow = BarcodeFlowable(code_value, width=doc.width, height=26 * mm)
    elements.append(barcode_flow)
    elements.append(Spacer(1, 8))

    # ------------------------------------------------------------
    # 🟦 HEADER XANH (TIÊU ĐỀ)
    # ------------------------------------------------------------
    class HeaderSmall(Flowable):
        def __init__(self, width, height=16 * mm):
            super().__init__()
            self.width = width
            self.height = height

        def draw(self):
            c = self.canv
            c.setFillColorRGB(0.07, 0.35, 0.65)
            c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
            c.setFillColor(colors.white)
            c.setFont(title_font, 12)
            c.drawCentredString(self.width / 2, self.height / 2 - 4, "BIÊN LAI THANH TOÁN LƯƠNG")

    elements.append(HeaderSmall(doc.width, 14 * mm))
    elements.append(Spacer(1, 10))

    # ------------------------------------------------------------
    # 📋 BẢNG THÔNG TIN GIAO DỊCH
    # ------------------------------------------------------------
    data = [
        ["Mã giao dịch:", txid],
        ["Mã nhân viên:", ma_nv],
        ["Họ và tên:", ho_ten],
        ["Số tiền:", f"{so_tien:,.0f} VNĐ"],
    ]
    if so_tk:
        data.append(["Số tài khoản:", so_tk])
    if ngan_hang:
        data.append(["Ngân hàng:", ngan_hang])
    data.extend([
        ["Phí giao dịch:", f"{phi:,.0f} VNĐ"],
        ["Phương thức:", phuong_thuc.capitalize()],
        ["Thời gian:", datetime.now().strftime("%d/%m/%Y %H:%M:%S")]
    ])

    table = Table(data, colWidths=[120, doc.width - 120])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), title_font),
        ("FONTSIZE", (0, 0), (-1, -1), 12),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE")
    ]))
    elements.append(table)
    elements.append(Spacer(1, 18))

    # ------------------------------------------------------------
    # 🔲 QR CODE
    # ------------------------------------------------------------
    qr_data = qr_target if qr_target else json.dumps({
        "txid": txid,
        "ma_nv": ma_nv,
        "amount": int(so_tien)
    })
    try:
        qr_code = qr.QrCodeWidget(qr_data)
        d = Drawing(60, 60)
        d.add(qr_code)
        elements.append(d)
    except Exception:
        pass

    elements.append(Spacer(1, 10))

    # ------------------------------------------------------------
    # ✍️ CHỮ KÝ + FOOTER
    # ------------------------------------------------------------
    if signature_img_path and os.path.exists(signature_img_path):
        elements.append(Image(signature_img_path, width=50 * mm, height=20 * mm))
        elements.append(Spacer(1, 6))

    elements.append(Paragraph("<i>Người thực hiện: Bộ phận Nhân sự - FaceID System</i>", style_body))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("Cảm ơn bạn đã làm việc chăm chỉ và đồng hành cùng <b>FaceID System</b>.", style_footer))

    # ------------------------------------------------------------
    # 💧 WATERMARK + PAGE NUMBER
    # ------------------------------------------------------------
    def _on_page(c, d):
        c.saveState()
        c.setFillColorRGB(0.90, 0.90, 0.90)
        if hasattr(c, "setFillAlpha"):
            c.setFillAlpha(0.12)
        c.translate(d.leftMargin + d.width / 2, d.bottomMargin + d.height / 2)
        c.rotate(30)
        c.setFont(title_font, 36)
        c.drawCentredString(0, 0, "FaceID System")
        c.restoreState()

        c.saveState()
        c.setFont(title_font, 9)
        c.setFillColor(colors.grey)
        c.drawRightString(d.leftMargin + d.width, 12, f"Trang {c.getPageNumber()}")
        c.restoreState()

    # ------------------------------------------------------------
    # 🧾 XUẤT FILE PDF
    # ------------------------------------------------------------
    doc.build(elements, onFirstPage=_on_page, onLaterPages=_on_page)

    # ------------------------------------------------------------
    # 💾 LƯU DÒNG GIAO DỊCH VÀO CSV
    # ------------------------------------------------------------
    try:
        csv_path = os.path.join(os.getcwd(), "receipts", "payments_log.csv")
        save_payment_record_csv(
            csv_path,
            txid, ma_nv, so_tk or "", ngan_hang or "",
            phuong_thuc, so_tien, phi,
            datetime.now()
        )
        print(f"📄 Đã lưu giao dịch vào CSV: {csv_path}")
    except Exception as e:
        print(f"[⚠️] Không thể lưu CSV: {e}")

    return file_path
