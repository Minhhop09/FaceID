import os
import shutil
import pyodbc

# ==============================
# 🔹 CẤU HÌNH
# ==============================
PHOTO_DIR = r"D:\faceid\photos"
BACKUP_DIR = os.path.join(PHOTO_DIR, "backup_before_rename")
DB_CONNECTION = r"DRIVER={SQL Server};SERVER=.\SQLEXPRESS;DATABASE=FaceID;Trusted_Connection=yes;"

# ==============================
# 🔹 KẾT NỐI CSDL
# ==============================
conn = pyodbc.connect(DB_CONNECTION)
cursor = conn.cursor()

# Tạo thư mục backup nếu chưa có
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)
    print(f"📁 Đã tạo thư mục backup: {BACKUP_DIR}")

cursor.execute("SELECT FaceID, MaNV, DuongDanAnh FROM KhuonMat WHERE TrangThai = 1")
rows = cursor.fetchall()
print(f"🔍 Tìm thấy {len(rows)} bản ghi cần xử lý...\n")

for row in rows:
    face_id, ma_nv, old_path = row
    old_filename = os.path.basename(old_path)
    old_file_path = os.path.join(PHOTO_DIR, old_filename)
    new_filename = f"{ma_nv}.jpg"
    new_file_path = os.path.join(PHOTO_DIR, new_filename)

    try:
        if not os.path.exists(old_file_path):
            print(f"⚠️ File không tồn tại: {old_filename}")
            continue

        # Backup ảnh cũ
        backup_path = os.path.join(BACKUP_DIR, old_filename)
        if not os.path.exists(backup_path):
            shutil.copy2(old_file_path, backup_path)

        # Kiểm tra trùng tên
        if os.path.exists(new_file_path) and old_file_path.lower() != new_file_path.lower():
            print(f"⚠️ Bỏ qua {old_filename} → {new_filename} (đã tồn tại)")
            continue

        # Đổi tên file
        os.rename(old_file_path, new_file_path)
        print(f"✅ Đã đổi {old_filename} -> {new_filename}")

        # Cập nhật SQL
        new_relative_path = f"photos/{new_filename}"
        cursor.execute("""
            UPDATE KhuonMat
            SET DuongDanAnh = ?
            WHERE FaceID = ?
        """, (new_relative_path, face_id))

    except Exception as e:
        print(f"❌ Lỗi khi xử lý {old_filename}: {e}")

# Lưu thay đổi
conn.commit()
conn.close()
print("\n🎉 Hoàn tất cập nhật và backup an toàn!")
