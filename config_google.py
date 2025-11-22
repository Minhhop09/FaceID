# ============================================================
# ⚙️ CONFIG GOOGLE OAUTH2 - FaceID System
# ============================================================
import os
from dotenv import load_dotenv

# ------------------------------------------------------------
# 🔐 Đọc biến môi trường từ file .env (nếu có)
# ------------------------------------------------------------
load_dotenv()

# ------------------------------------------------------------
# 🌍 Cấu hình ứng dụng Flask-OAuthlib / Authlib
# ------------------------------------------------------------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_DISCOVERY_URL = (
    "https://accounts.google.com/.well-known/openid-configuration"
)

# ------------------------------------------------------------
# 🧭 URL callback (phải trùng với cấu hình trên Google Cloud)
# ------------------------------------------------------------
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:5000/login/google/authorize")

# ------------------------------------------------------------
# ✅ Hàm tiện ích kiểm tra cấu hình hợp lệ
# ------------------------------------------------------------
def print_google_config():
    print("=== GOOGLE OAUTH CONFIG ===")
    print(f"Client ID: {GOOGLE_CLIENT_ID[:10]}********")
    print(f"Redirect URI: {REDIRECT_URI}")
    print("============================")

