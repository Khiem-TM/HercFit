"""Các miền nghiệp vụ (xem docs/module-map.json).

Import bất kỳ package `domains.<name>.models` nào cũng đăng ký mọi model ORM trước
(domains.registry). Schema vẫn import được
mà không cần model SQLAlchemy, settings hay database.
"""
