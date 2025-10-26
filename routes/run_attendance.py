import cv2
import face_recognition
import pyodbc
from datetime import datetime

def run_attendance():
    # Kết nối SQL Server
    conn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};'
                          'SERVER=localhost;DATABASE=FaceID;UID=sa;PWD=123456')
    cursor = conn.cursor()

    # Load dữ liệu khuôn mặt đã lưu
    known_face_encodings = []  
    known_face_names = []      

    cursor.execute("SELECT MaNV, FaceEncoding FROM NhanVien WHERE FaceEncoding IS NOT NULL")
    for row in cursor.fetchall():
        ma_nv = row[0]
        encoding = eval(row[1])  # convert string về list
        known_face_encodings.append(encoding)
        known_face_names.append(ma_nv)

    video_capture = cv2.VideoCapture(0)

    while True:
        ret, frame = video_capture.read()
        if not ret:
            break

        # Resize về HD (1280x720) cho đẹp
        frame = cv2.resize(frame, (1280, 720))

        # Chuyển sang RGB cho face_recognition
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Nhận diện khuôn mặt
        face_locations = face_recognition.face_locations(rgb_frame)
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
            matches = face_recognition.compare_faces(known_face_encodings, face_encoding)
            name = "Unknown"

            if True in matches:
                best_match_index = matches.index(True)
                name = known_face_names[best_match_index]

            # Vẽ khung quanh mặt
            cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 3)
            cv2.putText(frame, name, (left, top - 15),
                        cv2.FONT_HERSHEY_DUPLEX, 1, (0, 255, 0), 2)

        # Hiển thị hướng dẫn trên màn hình
        cv2.putText(frame, "Press 'C' to check-in, 'Q' to quit", (30, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 3)

        cv2.imshow('Attendance System', frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('c'):
            if name != "Unknown":
                cursor.execute("INSERT INTO ChamCong (MaNV, ThoiGian) VALUES (?, GETDATE())", (name,))
                conn.commit()
                print(f"✅ {name} đã được chấm công vào lúc {datetime.now()}")
            else:
                print("❌ Không nhận diện được khuôn mặt!")
        elif key == ord('q'):
            break

    video_capture.release()
    cv2.destroyAllWindows()
    conn.close()
