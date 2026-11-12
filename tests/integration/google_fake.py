"""Google Health giả lập trong bộ nhớ: giữ data point theo loại, cấp tên như Google, ghi lại mọi lệnh tạo/xoá."""
from copy import deepcopy
from itertools import count

from integrations.google_health.client import GoogleHealthClient, Page


class FakeGoogle(GoogleHealthClient):
    def __init__(self):  # không gọi lớp cha: không có HTTP
        self.points: dict[str, dict[str, dict]] = {}
        self.created: list[tuple[str, str]] = []
        self.deleted: list[str] = []
        self.patched: list[str] = []
        self._ids = count(1)

    def put(self, data_type: str, payload: dict) -> str:
        """Thêm một điểm như thể Google đã lưu (ví dụ một lần tạo trước khi tiến trình HercFit sập)."""
        name = f"users/me/dataTypes/{data_type}/dataPoints/fake-{next(self._ids)}"
        self.points.setdefault(data_type, {})[name] = {**deepcopy(payload), "name": name}
        return name

    async def list_page(self, data_type, *, filter=None, page_size=1000, page_token=None, reconcile=False,
                        family=None):
        # Bộ lọc ngày do pull.fetch áp lại sau khi parse, nên trả mọi điểm của loại là đủ.
        return Page(list(deepcopy(self.points.get(data_type, {})).values()), None)

    async def daily_rollup_page(self, data_type, start, end_exclusive, *, page_size=90, page_token=None):
        return Page([], None)

    async def rollup_page(self, data_type, start, end, *, window_seconds, page_size=1000, page_token=None):
        return Page([], None)

    async def create_point(self, data_type, point):
        name = self.put(data_type, point)
        self.created.append((data_type, name))
        return {"done": True, "response": {"name": name}}

    async def patch_point(self, name, point):
        data_type = name.split("/")[3]
        self.points.setdefault(data_type, {})[name] = {**deepcopy(point), "name": name}
        self.patched.append(name)
        return {"done": True, "response": {**deepcopy(point), "name": name}}

    async def batch_delete(self, data_type, names):
        for name in names:
            self.points.get(data_type, {}).pop(name, None)
        self.deleted.extend(names)
        return {"done": True}
