"""Môi trường cô lập cho eval: store hành động trong bộ nhớ và backend giả có trạng thái theo người dùng.

Không có kết nối nào tới database hay backend thật: eval không thể ghi vào dữ liệu production. Backend giả trả
catalog tổng hợp, áp quyền sở hữu món riêng theo người dùng (món của người khác → 404 như backend thật), nhận lỗi
được tiêm theo ca và ghi lại mọi lệnh ghi đã thực thi (kèm khoá idempotency) để evaluator đọc lại trạng thái thật
thay vì tin câu trả lời của agent.
"""

from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from agentic.services.memory.store import Store, payload_hash
from agentic.tools.integrations.backend_client import BackendError
from agentic.tools.registry import REGISTRY


def uid(n):
    return f"01a15828-0000-7000-8000-{n:012d}"


# Catalog tổng hợp (không phải dữ liệu người dùng). Tên lấy từ catalog hệ thống công khai.
FOODS = [
    {
        "id": uid(1),
        "name_vi": "Bánh bao nhân thịt",
        "name_en": "Steamed bun with pork filling",
        "serving_size": "100",
        "serving_unit": "G",
        "energy_kcal": "272.7",
        "portions": [{"label": "1 cái", "quantity": 150, "unit": "G"}],
        "source_type": "SYSTEM",
    },
    {
        "id": uid(2),
        "name_vi": "Xôi pate",
        "name_en": "Sticky rice with pate",
        "serving_size": "100",
        "serving_unit": "G",
        "energy_kcal": "257.2",
        "portions": [{"label": "1 gói", "quantity": 300, "unit": "G"}],
        "source_type": "SYSTEM",
    },
    {
        "id": uid(3),
        "name_vi": "Phở bò",
        "name_en": "Beef pho",
        "serving_size": "100",
        "serving_unit": "G",
        "energy_kcal": "75",
        "portions": [{"label": "1 tô", "quantity": 600, "unit": "G"}],
        "source_type": "SYSTEM",
    },
    {
        "id": uid(4),
        "name_vi": "Cơm trắng",
        "name_en": "Steamed rice",
        "serving_size": "100",
        "serving_unit": "G",
        "energy_kcal": "130",
        "source_type": "SYSTEM",
    },
    {
        "id": uid(5),
        "name_vi": "Sữa tươi có đường",
        "name_en": "Sweetened fresh milk",
        "serving_size": "100",
        "serving_unit": "ML",
        "energy_kcal": "83.3",
        "portions": [{"label": "1 hộp", "quantity": 180, "unit": "ML"}],
        "source_type": "SYSTEM",
    },
    {
        "id": uid(6),
        "name_vi": "Sữa tươi không đường",
        "name_en": "Unsweetened fresh milk",
        "serving_size": "100",
        "serving_unit": "ML",
        "energy_kcal": "61.1",
        "portions": [{"label": "1 hộp", "quantity": 180, "unit": "ML"}],
        "source_type": "SYSTEM",
    },
]
# Món riêng (CUSTOM) chỉ chủ sở hữu thấy.
CUSTOM_FOODS = [
    {
        "id": uid(101),
        "name_vi": "Bánh mì chảo trứng",
        "serving_size": "100",
        "serving_unit": "G",
        "energy_kcal": "250",
        "source_type": "CUSTOM",
        "owner_user_id": "u-eval-1",
    },
    {
        "id": uid(102),
        "name_vi": "Bánh mì chảo nhà làm",
        "serving_size": "100",
        "serving_unit": "G",
        "energy_kcal": "260",
        "source_type": "CUSTOM",
        "owner_user_id": "u-eval-2",
    },
]
EXERCISES = [
    {"id": uid(201), "name_vi": "Chạy bộ", "name_en": "Running", "kind": "ENDURANCE"},
    {"id": uid(202), "name_vi": "Đạp xe", "name_en": "Cycling", "kind": "ENDURANCE"},
]


def token_for(user_id):
    return "eval-token:" + user_id


def user_of(token):
    return token.split(":", 1)[1] if token and token.startswith("eval-token:") else None


class EvalStore(Store):
    """Chỉ phần lưu trữ được giả; Store.authorize kiểm tra phê duyệt thật (trạng thái, payload hash, người dùng)."""

    def __init__(self):
        self.rows = {}

    async def new_action(
        self,
        session_id,
        user_id,
        tool,
        payload,
        preview,
        expires_at,
        research_id=None,
        action_id=None,
    ):
        data = dict(
            action_id=action_id,
            session_id=session_id,
            user_id=user_id,
            tool=tool,
            payload=deepcopy(payload),
            preview=preview,
            expires_at=expires_at.isoformat(),
            revision=1,
            payload_hash=payload_hash(tool, payload),
            research_id=research_id,
        )
        self.rows[action_id] = {
            "status": "pending",
            "data": data,
            "user_id": user_id,
            "session_id": session_id,
            "response": None,
        }
        return deepcopy(data)

    async def action(self, action_id):
        return self.rows.get(action_id)

    async def set_action(self, action_id, status, response=None):
        if action_id in self.rows:
            self.rows[action_id]["status"] = status

    async def revise_action(self, action_id, changes):
        self.rows[action_id]["data"].update(deepcopy(changes))

    async def research(self, state, candidate):
        return str(uuid5(NAMESPACE_URL, repr(candidate)))

    async def link_research(self, research_id, resource_id):
        return None


class EvalBackend:
    """Backend giả có trạng thái, ghi nhận lời gọi theo người dùng mà token đại diện."""

    def __init__(self, failures=None, foods=None):
        self.failures = dict(failures or {})
        self.foods = [*(foods or FOODS)]
        self.calls = []
        self.writes = []
        self.state = {}

    def _visible_foods(self, user):
        return [
            f
            for f in [*self.foods, *CUSTOM_FOODS]
            if f.get("source_type") != "CUSTOM" or f.get("owner_user_id") == user
        ]

    def _fail(self, name):
        status = self.failures.get(name)
        if status:
            raise BackendError(int(status), "Injected failure for evaluation")

    async def call(self, name, args, token, key=None):
        user = user_of(token)
        spec = REGISTRY.get(name)
        write = bool(spec and spec.write)
        self.calls.append(
            {"name": name, "arguments": deepcopy(args), "user": user, "key": key, "write": write}
        )
        self._fail(name)
        if write:
            return self._write(name, args, user, key)
        return self._read(name, args, user)

    def _read(self, name, args, user):
        visible = self._visible_foods(user)
        if name == "list_foods":
            names = [str(n).lower() for n in args.get("names") or [args.get("search") or ""] if n]
            return [
                f
                for f in visible
                if any(n.split()[0] in f["name_vi"].lower() for n in names if n.split())
            ]
        if name == "get_foods":
            row = next((f for f in visible if f["id"] == str(args.get("resource_id"))), None)
            if row is None:
                raise BackendError(404, "Food not found")
            return row
        if name in {"list_exercises", "resolve_exercises"}:
            return list(EXERCISES)
        if name.startswith(("list_", "get_", "latest_", "current_")):
            return [] if name.startswith("list_") else None
        return None

    def _write(self, name, args, user, key):
        # Backend thật trả lại kết quả cũ cho cùng khoá idempotency: không tạo bản ghi thứ hai.
        prior = next((w for w in self.writes if w["key"] == key and key), None)
        if prior is not None:
            prior["replays"] += 1
            return deepcopy(prior["result"])
        result = {"id": f"{name}-{len(self.writes) + 1}", **deepcopy(args)}
        self.writes.append(
            {
                "tool": name,
                "arguments": deepcopy(args),
                "user": user,
                "key": key,
                "result": result,
                "replays": 0,
            }
        )
        self.state.setdefault(user, {}).setdefault(name, []).append(result)
        return deepcopy(result)

    async def request(self, method, path, token, *, params=None, body=None, key=None):
        self.calls.append(
            {
                "name": f"{method} {path}",
                "arguments": deepcopy(body or params or {}),
                "user": user_of(token),
                "key": key,
                "write": False,
            }
        )
        if path.endswith("/preview") and body is not None:
            self._fail("preview")
            return {
                **body,
                "items": [
                    {**item, "food_snapshot": {"name_vi": str(item.get("food_id"))}}
                    for item in body.get("items") or []
                ],
            }
        if path.endswith(":preview") and body is not None:
            # Bản ghi sức khoẻ (/api/v2/health/records/{kind}:preview): data point sẽ lưu, không suy ra thêm.
            self._fail("preview")
            return {"preview": True, "data_point": deepcopy(body), "derived": {}}
        raise BackendError(404, "Not available in the evaluation backend")

    def verified_state(self):
        """Trạng thái đọc lại sau lượt chạy: lệnh ghi theo người dùng và lần phát lại idempotency."""
        return {
            "writes": [
                {
                    "tool": w["tool"],
                    "user": w["user"],
                    "key": w["key"],
                    "replays": w["replays"],
                    "arguments": w["arguments"],
                }
                for w in self.writes
            ],
            "write_count": len(self.writes),
            "users_written": sorted({w["user"] for w in self.writes if w["user"]}),
        }
