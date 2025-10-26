import schedule
import time
import threading
from auto_notify_shift_end import send_mail_remind_unchecked_shift

def job_loop(app):
    """Luồng chạy nền để kiểm tra định kỳ"""
    print("🚀 Bắt đầu theo dõi ca làm việc (scheduler)...")

    # Chạy ngay 1 lần khi khởi động
    send_mail_remind_unchecked_shift(app)

    # Sau đó lặp lại mỗi 10 phút
    schedule.every(10).minutes.do(lambda: send_mail_remind_unchecked_shift(app))

    while True:
        schedule.run_pending()
        time.sleep(60)

def start_scheduler(app):
    """Khởi chạy scheduler trong thread riêng"""
    thread = threading.Thread(target=job_loop, args=(app,), daemon=True)
    thread.start()
    print("✅ Scheduler đã khởi động trong background")
