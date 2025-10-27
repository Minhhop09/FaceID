from functools import wraps
from flask import session, redirect, url_for, flash

def require_role(*roles):
    """
    Decorator kiểm tra quyền truy cập trang theo vai trò người dùng.
    Có thể dùng:
      @require_role("admin")
      @require_role("admin", "hr")
      @require_role(["admin", "hr"])
      @require_role(("admin", "hr"))
    """

    def _flatten(iterable):
        for x in iterable:
            if isinstance(x, (list, tuple, set)):
                for y in _flatten(x):
                    yield y
            else:
                yield x

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # ======================================================
            # 🔒 1. Kiểm tra đã đăng nhập hay chưa
            # ======================================================
            username = session.get("username")
            user_id = session.get("user_id")
            current_role = session.get("role")

            if not (username or user_id):
                flash("Vui lòng đăng nhập để truy cập hệ thống", "warning")
                return redirect(url_for("auth_bp.login"))

            # ======================================================
            # 🧩 2. Chuẩn hoá danh sách role cho phép
            # ======================================================
            flat_roles = list(_flatten(roles))
            allowed = [str(r).strip().lower() for r in flat_roles if r]
            allowed_set = set(allowed)

            # ======================================================
            # 🪪 3. Ghi log để debug
            # ======================================================
            print(
                f">>> ROLE IN SESSION: {current_role!r} | RAW ROLES: {roles!r} "
                f"| FLAT: {flat_roles!r} | ALLOWED: {allowed_set!r}"
            )

            # ======================================================
            # 🚫 4. Kiểm tra quyền
            # ======================================================
            if not current_role or current_role.strip().lower() not in allowed_set:
                flash("Bạn không có quyền truy cập trang này!", "danger")
                return redirect(url_for("index"))

            # ======================================================
            # ✅ 5. Cho phép truy cập
            # ======================================================
            return f(*args, **kwargs)

        return wrapper
    return decorator
