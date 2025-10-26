from core.db_utils import get_connection
import hashlib

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_accounts():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM TaiKhoan")
    data = cursor.fetchall()
    conn.close()
    return data

def add_account(username, hashed_password, role):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO TaiKhoan (TenDangNhap, MatKhauHash, VaiTro, TrangThai, NgayTao)
        VALUES (?, ?, ?, 1, GETDATE())
    """, (username, hashed_password, role))
    
    conn.commit()
    conn.close()


def update_account(username, password=None, role=None):
    conn = get_connection()
    cursor = conn.cursor()
    if password:
        cursor.execute("UPDATE TaiKhoan SET Password=?, Role=? WHERE Username=?",
                       (hash_password(password), role, username))
    else:
        cursor.execute("UPDATE TaiKhoan SET Role=? WHERE Username=?", (role, username))
    conn.commit()
    conn.close()

def delete_account(username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM TaiKhoan WHERE Username=?", (username,))
    conn.commit()
    conn.close()
