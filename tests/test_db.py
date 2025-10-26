from core.db_utils import get_connection

conn = get_connection()
if conn:
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sys.tables;")
    tables = cursor.fetchall()
    print("Danh sách bảng trong DB FaceID:")
    for t in tables:
        print("-", t[0])
    conn.close()
