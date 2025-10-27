from decimal import Decimal
from core.payment_utils import generate_salary_pdf
import os, random, string

# Sinh mã giao dịch ngẫu nhiên
tx = "TX" + ''.join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", k=10))

# Đường dẫn lưu file PDF
pdf_path = os.path.join("D:/faceid/receipts", f"receipt_{tx}.pdf")

# Gọi hàm tạo biên lai
out = generate_salary_pdf(
    txid=tx,
    ma_nv="NV00005",
    ho_ten="Trần Minh Hợp",
    so_tien=Decimal("30500000"),
    phuong_thuc="bank",
    phi=Decimal("3300"),
    file_path=pdf_path,
    signature_img_path="D:/faceid/static/images/signature_hr.png",
    qr_target=f"https://faceid.local/receipts/{tx}"
)

print("✅ PDF đã tạo:", out)
