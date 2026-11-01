"""Nhà cung cấp bên ngoài. Chỉ package này giao tiếp với API sức khoẻ bên thứ ba.

Model của tích hợp (health_connections, ...) thuộc registry ORM; nạp registry
trước để import trực tiếp một trong số chúng không gây import vòng. Sau đó mỗi
nhà cung cấp đăng ký bản cài đặt các port của miền.
"""
import domains.registry  # noqa: F401
import integrations.google_health.directory  # noqa: E402,F401
