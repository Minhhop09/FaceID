import pyodbc
from core.db_utils import get_sql_connection

def cap_nhat_vang_va_phep():
    """
    ✅ Cập nhật trạng thái vắng cho nhân viên:
    - Nếu đã qua giờ kết thúc ca mà chưa chấm công → tự động chèn bản ghi ChamCong ('Không chấm công')
    - Cập nhật LichLamViec.TrangThai = 2 (Vắng)
    - Chỉ cập nhật 1 lần / nhân viên / ca / ngày (tránh trùng)
    - Áp dụng cho cả ca đã qua hôm trước hoặc ca hôm nay đã kết thúc
    """
    conn = None
    try:
        conn = get_sql_connection()
        cursor = conn.cursor()

        # 1️⃣ Thêm bản ghi chấm công "Không chấm công" nếu chưa có
        cursor.execute("""
            INSERT INTO ChamCong (MaNV, MaLLV, MaCa, NgayChamCong, TrangThai, DaXoa, GhiChu)
            SELECT 
                LLV.MaNV, LLV.MaLLV, LLV.MaCa, LLV.NgayLam,
                0 AS TrangThai,      -- 0 = vắng
                1 AS DaXoa,          -- 1 = hiển thị
                N'Không chấm công' AS GhiChu
            FROM LichLamViec LLV
            JOIN CaLamViec CLV ON LLV.MaCa = CLV.MaCa
            LEFT JOIN ChamCong CC
                ON CC.MaNV = LLV.MaNV
               AND CC.MaCa = LLV.MaCa
               AND CC.NgayChamCong = LLV.NgayLam
            WHERE CC.MaChamCong IS NULL                -- chưa có chấm công
              AND LLV.TrangThai = 0                   -- chưa cập nhật
              AND LLV.DaXoa = 1                       -- không bị ẩn
              AND (
                    LLV.NgayLam < CAST(GETDATE() AS DATE)
                    OR (
                        LLV.NgayLam = CAST(GETDATE() AS DATE)
                        AND CAST(GETDATE() AS TIME) >= CLV.GioKetThuc -- ca đã kết thúc
                     )
                  );
        """)

        # 2️⃣ Cập nhật LichLamViec.TrangThai = 2 (Vắng)
        cursor.execute("""
            UPDATE LLV
            SET LLV.TrangThai = 2  -- 2 = Vắng
            FROM LichLamViec LLV
            JOIN CaLamViec CLV ON LLV.MaCa = CLV.MaCa
            LEFT JOIN ChamCong CC
                ON CC.MaNV = LLV.MaNV
               AND CC.MaCa = LLV.MaCa
               AND CC.NgayChamCong = LLV.NgayLam
            WHERE LLV.DaXoa = 1
              AND LLV.TrangThai = 0                   -- chỉ cập nhật những ca chưa đóng
              AND (
                    LLV.NgayLam < CAST(GETDATE() AS DATE)
                    OR (
                        LLV.NgayLam = CAST(GETDATE() AS DATE)
                        AND CAST(GETDATE() AS TIME) >= CLV.GioKetThuc
                     )
                  )
              AND CC.MaChamCong IS NULL;              -- chưa có dòng chấm công
        """)

        conn.commit()
        print("✅ Đã cập nhật trạng thái vắng và ghi chấm công 'Không chấm công' cho nhân viên chưa chấm hôm nay / hôm trước.")

    except Exception as e:
        if conn:
            conn.rollback()
        print(f"❌ Lỗi khi cập nhật vắng hoặc phép: {e}")

    finally:
        if conn:
            conn.close()
