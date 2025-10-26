from functools import wraps
from flask import session, redirect, url_for, flash

def require_role(*roles):
    """
    Dùng:
      @require_role("admin")
      @require_role("admin", "hr")
      @require_role(["admin", "hr"])
      @require_role(("admin", "hr"))
      @require_role([["admin", "hr"], "qlpb"])
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
            # 1) Chưa đăng nhập
            if "username" not in session:
                flash("Vui lòng đăng nhập để truy cập hệ thống", "warning")
                return redirect(url_for("auth_bp.login"))

            current_role = session.get("role")

            # 2) Làm phẳng & chuẩn hoá danh sách roles cho phép
            #    (đưa hết về chữ thường và lọc None/rỗng)
            flat = list(_flatten(roles))
            allowed = [str(r).strip().lower() for r in flat if r is not None and str(r).strip() != ""]
            allowed_set = set(allowed)

            # Log chẩn đoán (rất quan trọng để bạn thấy còn list lồng không)
            print(f">>> ROLE IN SESSION: {current_role!r} | RAW ROLES: {roles!r} | FLAT: {flat!r} | ALLOWED: {allowed_set!r}")

            # 3) So khớp quyền (không phân biệt hoa/thường)
            if not current_role or current_role.strip().lower() not in allowed_set:
                flash("Bạn không có quyền truy cập trang này!", "danger")
                return redirect(url_for("index"))

            return f(*args, **kwargs)
        return wrapper
    return decorator
