import threading
import time
import datetime
import schedule  # 🟢 Quan trọng: thêm import này
from core.db import get_sql_connection
from core.offline_cache import sync_offline_data
from core.email_utils import send_email_notification, notify_attendance


# ============================================================
# 🕒 1️⃣ Luồng nền đồng bộ dữ liệu offline mỗi 5 phút
# ============================================================
def background_sync():
    """Chạy luồng nền tự động đồng bộ offline → SQL"""
    while True:
        try:
            conn = get_sql_connection()
            sync_offline_data(conn)
            conn.close()
            print("[SYNC] ✅ Đồng bộ dữ liệu offline → SQL thành công.")
        except Exception as e:
            print(f"[SYNC] ⚠️ Không thể kết nối SQL: {e}")
        time.sleep(300)  # 5 phút


# ============================================================
# 🌙 2️⃣ Tự đồng bộ nghỉ phép vào 23h mỗi ngày
# ============================================================
def auto_sync_leaves():
    """Chạy mỗi đêm để tự đồng bộ nghỉ phép (LichLamViec + ChamCong)"""
    print(f"[AUTO_SYNC] 🚀 Bắt đầu đồng bộ nghỉ phép lúc {datetime.datetime.now()}")
    try:
        conn = get_sql_connection()
        cur = conn.cursor()

        # Cập nhật lịch làm việc có đơn phép duyệt nhưng chưa sync
        cur.execute("""
            UPDATE LLV
            SET TrangThai = 3
            FROM LichLamViec LLV
            INNER JOIN DonNghiPhep_CaLam C 
                ON LLV.MaCa = C.MaCa AND CONVERT(date, LLV.NgayLam) = CONVERT(date, C.NgayNghi)
            INNER JOIN DonNghiPhep D 
                ON D.MaDon = C.MaDon AND LLV.MaNV = D.MaNV
            WHERE D.TrangThaiDuyet = N'Đã duyệt'
              AND (LLV.TrangThai IS NULL OR LLV.TrangThai NOT IN (1,2,3))
              AND (LLV.DaXoa = 0 OR LLV.DaXoa IS NULL);
        """)

        # Đồng bộ sang ChamCong (nếu thiếu)
        cur.execute("""
            INSERT INTO ChamCong (MaNV, NgayChamCong, MaCa, TrangThai, CoDon, DaXoa)
            SELECT DISTINCT D.MaNV, CONVERT(date, C.NgayNghi), C.MaCa, 3, 1, 1
            FROM DonNghiPhep D
            INNER JOIN DonNghiPhep_CaLam C ON D.MaDon = C.MaDon
            WHERE D.TrangThaiDuyet = N'Đã duyệt'
              AND CONVERT(date, C.NgayNghi) = CAST(GETDATE() AS DATE)
              AND NOT EXISTS (
                  SELECT 1 FROM ChamCong CC
                  WHERE CC.MaNV = D.MaNV 
                    AND CONVERT(date, CC.NgayChamCong) = CONVERT(date, C.NgayNghi)
                    AND CC.MaCa = C.MaCa
              );
        """)

        conn.commit()
        conn.close()
        print("[AUTO_SYNC] ✅ Hoàn tất đồng bộ nghỉ phép đêm nay.")
    except Exception as e:
        print(f"[AUTO_SYNC] ❌ Lỗi đồng bộ nghỉ phép: {e}")


# ============================================================
# ⏰ 3️⃣ Lên lịch tự chạy 23h mỗi ngày
# ============================================================
def schedule_runner():
    """Luồng chạy schedule định kỳ"""
    schedule.every().day.at("23:00").do(auto_sync_leaves)
    print("🕓 Scheduler đã khởi động — sẽ đồng bộ nghỉ phép mỗi 23:00 hàng ngày.")
    while True:
        schedule.run_pending()
        time.sleep(60)


# ============================================================
# 🚀 4️⃣ Khởi động song song khi Flask app khởi chạy
# ============================================================
threading.Thread(target=background_sync, daemon=True).start()
threading.Thread(target=schedule_runner, daemon=True).start()
