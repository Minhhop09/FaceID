import core.face_utils as face_utils

# Test hàm get_face_embedding
embedding = face_utils.get_face_embedding("test_face.jpg")
if embedding is not None:
    print("Đã tìm thấy khuôn mặt!")
    print(f"Kích thước embedding: {embedding.shape}")
    print(f"Giá trị embedding đầu tiên: {embedding[:5]}...")  # Hiển thị 5 giá trị đầu
else:
    print("Không tìm thấy khuôn mặt trong ảnh!")