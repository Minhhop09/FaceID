import os
import pyodbc

# --- Kết nối database ---
conn = pyodbc.connect(
    "Driver={SQL Server};"
        "Server=MINHHOP\\SQLEXPRESS;"
        "Database=FaceID;"
        "UID=sa;PWD=123456"
)
cursor = conn.cursor()

# --- Thư mục chứa ảnh ---
PHOTOS_DIR = "photos"

# --- Lấy danh sách MaNV và MaHienThi từ DB ---
cursor.execute("SELECT MaNV, MaHienThi FROM NhanVien")
rows = cursor.fetchall()

renamed = 0
not_found = 0

for ma_nv, ma_hienthi in rows:
    old_path_1 = os.path.join(PHOTOS_DIR, f"{ma_hienthi}.jpg")  # kiểu cũ: NVCN1.jpg
    old_path_2 = os.path.join(PHOTOS_DIR, f"{ma_nv.replace('NV', '')}.jpg")  # nếu ảnh cũ là 00001.jpg
    new_path = os.path.join(PHOTOS_DIR, f"{ma_nv}.jpg")

    if os.path.exists(old_path_1):
        os.rename(old_path_1, new_path)
        renamed += 1
        print(f"✅ {old_path_1} → {new_path}")
    elif os.path.exists(old_path_2):
        os.rename(old_path_2, new_path)
        renamed += 1
        print(f"✅ {old_path_2} → {new_path}")
    elif not os.path.exists(new_path):
        not_found += 1
        print(f"⚠️ Không tìm thấy ảnh cho {ma_nv} ({ma_hienthi})")

print(f"\n🔁 Đổi tên hoàn tất: {renamed} ảnh ✅, {not_found} không tìm thấy ⚠️")

conn.close()
