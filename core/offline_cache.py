# ============================================================
# core/offline_cache.py — FINAL FIXED v2 (Production Ready)
# ------------------------------------------------------------
# ✅ Tạo và quản lý cache SQLite để lưu chấm công khi mất mạng
# ✅ Đồng bộ lại khi online (SQL Server / Firebase)
# ✅ An toàn, tự động khởi tạo bảng nếu bị xóa
# ============================================================

import sqlite3
from datetime import datetime
import time
import threading

DB_PATH = "offline_cache.db"


# ============================================================
# 1️⃣ Hàm khởi tạo & kết nối an toàn
# ============================================================
def get_local_conn():
    """Mở kết nối SQLite với timeout để tránh database locked"""
    return sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)


def ensure_table_exists(conn):
    """Đảm bảo bảng OfflineAttendance tồn tại"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS OfflineAttendance (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            MaNV TEXT,
            Ngay TEXT,
            Ca TEXT,
            GioVao TEXT,
            GioRa TEXT,
            Latitude REAL,
            Longitude REAL,
            Synced INTEGER DEFAULT 0,
            ErrorMsg TEXT DEFAULT NULL,
            CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def init_local_cache():
    """Khởi tạo file SQLite để lưu chấm công tạm"""
    conn = get_local_conn()
    ensure_table_exists(conn)
    conn.close()
    print("[INIT] ✅ SQLite offline cache sẵn sàng.")


# ============================================================
# 2️⃣ Lưu bản ghi offline khi mất mạng
# ============================================================
def save_offline_record(ma_nv, ngay, ca, gio_vao, lat=None, lon=None, gio_ra=None):
    """Lưu bản ghi tạm khi SQL Server mất kết nối"""
    try:
        conn = get_local_conn()
        ensure_table_exists(conn)
        conn.execute("""
            INSERT INTO OfflineAttendance (MaNV, Ngay, Ca, GioVao, GioRa, Latitude, Longitude, Synced)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (ma_nv, ngay, ca, gio_vao, gio_ra, lat, lon))
        conn.commit()
        conn.close()
        print(f"[OFFLINE] 💾 Đã lưu tạm {ma_nv} ({ca}) vào offline_cache.db")
    except Exception as e:
        print(f"[OFFLINE] ❌ Không thể lưu cache: {e}")


# ============================================================
# 3️⃣ Đồng bộ dữ liệu offline lên SQL Server
# ============================================================
def sync_offline_data(sql_conn):
    """Đồng bộ dữ liệu từ SQLite lên SQL Server"""
    local_conn = get_local_conn()
    ensure_table_exists(local_conn)
    cursor_local = local_conn.cursor()

    rows = cursor_local.execute("SELECT * FROM OfflineAttendance WHERE Synced=0").fetchall()
    if not rows:
        print("[SYNC] ✅ Không có bản ghi cần đồng bộ.")
        local_conn.close()
        return

    print(f"[SYNC] 🔄 Bắt đầu đồng bộ {len(rows)} bản ghi...")
    cursor_remote = sql_conn.cursor()
    synced = 0

    for r in rows:
        (ID, ma_nv, ngay, ca, gio_vao, gio_ra, lat, lon, synced_flag, error_msg, created_at) = r
        try:
            # Ghi vào SQL Server
            cursor_remote.execute("""
                INSERT INTO ChamCong (MaNV, NgayChamCong, MaCa, GioVao, GioRa, TrangThai)
                VALUES (?, ?, ?, ?, ?, 4)
            """, (ma_nv, ngay, ca, gio_vao, gio_ra))
            sql_conn.commit()

            # ===============================
            # ✉️ Gửi email xác nhận khi đồng bộ thành công
            # ===============================
            try:
                from core.email_utils import notify_attendance
                from flask import current_app, Flask
                from flask_mail import Mail

                # 🔹 Thử lấy Flask app context đang chạy
                try:
                    app = current_app._get_current_object()
                except Exception:
                    # 🔸 Nếu không có (ví dụ: đang chạy thread background)
                    app = Flask(__name__)
                    app.config.update(
                        MAIL_SERVER='smtp.gmail.com',
                        MAIL_PORT=587,
                        MAIL_USE_TLS=True,
                        MAIL_USERNAME='faceid.system@gmail.com',
                        MAIL_PASSWORD='bdrs phlg crme xrpf',
                        MAIL_DEFAULT_SENDER=('FaceID System', 'faceid.system@gmail.com'),
                    )
                    Mail(app)

                # 🔹 Từ tuple r = (ID, MaNV, Ngay, Ca, GioVao, GioRa, ...)
                ma_ca = ca
                gio = gio_ra or gio_vao or "—"

                notify_attendance(
                    ma_nv,
                    "Đồng bộ lại (offline → online)",
                    gio,
                    ma_ca=ma_ca,
                    source="sync",
                    app=app
                )
                print(f"[SYNC][MAIL] ✅ Đã gửi lại email xác nhận cho {ma_nv} ({ma_ca})")

            except Exception as e:
                print(f"[SYNC][MAIL] ⚠️ Không thể gửi mail khi đồng bộ: {e}")


            # Cập nhật trạng thái đã đồng bộ
            cursor_local.execute(
                "UPDATE OfflineAttendance SET Synced=1, ErrorMsg=NULL WHERE ID=?",
                (ID,)
            )
            synced += 1
            print(f"[SYNC] ✅ {ma_nv}-{ca} đã đồng bộ lên SQL Server.")
        except Exception as e:
            cursor_local.execute(
                "UPDATE OfflineAttendance SET ErrorMsg=? WHERE ID=?",
                (str(e), ID)
            )
            print(f"[SYNC] ❌ Lỗi đồng bộ {ma_nv}-{ca}: {e}")

    local_conn.commit()
    local_conn.close()
    print(f"[SYNC] 🎯 Hoàn tất: {synced}/{len(rows)} bản ghi đã được đồng bộ.")


# ============================================================
# 4️⃣ Vòng lặp chạy nền — auto sync mỗi X phút
# ============================================================
def background_sync_loop(get_sql_connection_func, interval_sec=300):
    """
    Chạy vòng lặp nền tự động đồng bộ (mặc định 5 phút).
    Truyền hàm get_sql_connection() từ core.db vào để dùng.
    """
    def loop():
        while True:
            try:
                conn = get_sql_connection_func()
                sync_offline_data(conn)
                conn.close()
            except Exception as e:
                print(f"[SYNC] ⚠️ Không thể kết nối SQL Server: {e}")
            time.sleep(interval_sec)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    print(f"[SYNC] 🕒 Bật auto sync mỗi {interval_sec/60:.0f} phút.")
