from core.face_utils import get_face_embedding
from core.db_utils import insert_face_embedding
import os
import re

folder = "photos"
for file in os.listdir(folder):
    if file.endswith(".jpg"):
        path = os.path.join(folder, file)
        # Lấy ID số từ tên file: person<ID>_timestamp.jpg
        match = re.match(r"person(\d+)_\d+\.jpg", file)
        if match:
            nhanvien_id = int(match.group(1))  # chỉ lấy số ID
            embedding = get_face_embedding(path)
            if embedding is not None:
                insert_face_embedding(nhanvien_id, path, embedding)
                print(f"✅ Đăng ký khuôn mặt nhân viên {nhanvien_id} từ file {file}")
        else:
            print(f"⚠️ Bỏ qua file không đúng chuẩn: {file}")
