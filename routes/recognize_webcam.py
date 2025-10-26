import cv2
import numpy as np
import face_recognition
from core.db_utils import get_connection

# ==============================
# 1. Lấy tất cả embedding từ DB
# ==============================
def load_embeddings_from_db():
    conn = get_connection()
    if conn is None:
        return [], []
    cursor = conn.cursor()
    cursor.execute("SELECT NhanVienID, FaceEncoding FROM KhuonMat")
    ids = []
    embeddings = []
    for row in cursor.fetchall():
        ids.append(row[0])
        enc = np.frombuffer(row[1], dtype=np.float32)  # convert bytes -> numpy array
        embeddings.append(enc)
    conn.close()
    return ids, embeddings

# ==============================
# 2. Nhận diện khuôn mặt trực tiếp
# ==============================
def recognize_from_webcam():
    ids, known_embeddings = load_embeddings_from_db()
    if len(ids) == 0:
        print("❌ Chưa có embedding nào trong DB!")
        return

    cap = cv2.VideoCapture(0)
    print("📷 Bắt đầu webcam... Nhấn 'q' để thoát.")

    while True:
        ret, frame = cap.read()
        if not ret:
            continue

        # Resize frame để tăng tốc
        small_frame = cv2.resize(frame, (0,0), fx=0.25, fy=0.25)
        rgb_small_frame = small_frame[:, :, ::-1]  # BGR -> RGB

        # Phát hiện khuôn mặt và tính embedding
        face_locations = face_recognition.face_locations(rgb_small_frame)
        face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
            # So sánh với các embedding đã lưu
            matches = face_recognition.compare_faces(known_embeddings, face_encoding, tolerance=0.5)
            name = "Unknown"
            if True in matches:
                match_index = matches.index(True)
                name = str(ids[match_index])  # Hiển thị NhanVienID, sau này có thể lấy tên từ bảng NhanVien

            # Vẽ khung và tên
            top *= 4
            right *= 4
            bottom *= 4
            left *= 4
            cv2.rectangle(frame, (left, top), (right, bottom), (0,255,0), 2)
            cv2.putText(frame, name, (left, top-10), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0), 2)

        cv2.imshow("FaceID Recognition", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

# ==============================
# 3. Chạy chương trình
# ==============================
if __name__ == "__main__":
    recognize_from_webcam()
