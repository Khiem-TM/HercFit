# Nạp toàn bộ model ORM (domains.registry) trước mọi module của miền, để đích quan hệ và hook graph-outbox luôn
# đầy đủ dù chỉ import một model.
import domains.registry  # noqa: F401
