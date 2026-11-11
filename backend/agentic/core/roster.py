"""Danh sách agent của kiến trúc multi-agent và agent đang chạy.

Supervisor (node orchestrator) phân loại yêu cầu một lần rồi giao cho agent chuyên trách sở hữu miền của quyết định;
research tra cứu nguồn đã kiểm chứng; synthesizer (node answer) viết câu trả lời. clarify và memory là agent tiện ích
gắn với vai trò model của chúng, dù node nào gọi.

Mỗi agent có thể dùng model riêng (AGENT_MODELS). Agent đang chạy được đặt bằng biến ngữ cảnh cho đúng node đó, nên
Models và số đo telemetry biết lời gọi model thuộc agent nào mà không đổi chữ ký get(role).
"""
from contextlib import contextmanager
from contextvars import ContextVar

SUPERVISOR, RESEARCH, SYNTHESIZER = 'supervisor', 'research', 'synthesizer'
NUTRITION, TRAINING_LOG, BODY_HEALTH, COACH = 'nutrition', 'training_log', 'body_health', 'coach'
DAILY_HEALTH = 'daily_health'
# Viết lời thông báo chủ động (cảnh báo chỉ số, đánh giá ngày) từ dữ liệu backend đã tính; không ở trong đồ thị chat.
NOTIFIER = 'notifier'
# Viết Cypher chỉ đọc lấy context graph cho một câu hỏi (knowledge_graph/context); chỉ chạy khi chưa có mẫu phù hợp.
CONTEXT = 'context'

# Miền nghiệp vụ mỗi agent chuyên trách sở hữu: tool của miền, đường nhanh và luật tiếp nối của nó.
SPECIALIST_DOMAINS = {
    NUTRITION: frozenset({'meals', 'foods'}),
    TRAINING_LOG: frozenset({'trainings', 'exercises'}),
    BODY_HEALTH: frozenset({'metrics', 'progress', 'profile'}),
    COACH: frozenset({'training_plans', 'goals', 'coaching'}),
    # Daily Health Intelligence: chỉ đọc dữ liệu thiết bị và đánh giá hằng ngày tất định của backend, không ghi.
    DAILY_HEALTH: frozenset({'health'}),
}
# Vai trò model là agent tiện ích của riêng nó, dù node nào gọi.
ROLE_AGENTS = {'clarify': 'clarify', 'summary': 'memory'}
AGENTS = frozenset({SUPERVISOR, *SPECIALIST_DOMAINS, RESEARCH, SYNTHESIZER, NOTIFIER, CONTEXT, *ROLE_AGENTS.values()})

active: ContextVar[str | None] = ContextVar('active_agent', default=None)
# Lần thử lại đã nâng cấp: bỏ qua model riêng của agent, dùng model của vai trò.
_escalated: ContextVar[bool] = ContextVar('agent_escalated', default=False)


def specialist_for(domain):
    """Agent chuyên trách sở hữu miền này, hoặc None."""
    return next((name for name, domains in SPECIALIST_DOMAINS.items() if domain in domains), None)


def agent_for(role):
    return ROLE_AGENTS.get(role) or active.get()


def assigned_model(settings, role):
    """Model riêng của agent đang gọi vai trò này; None khi agent dùng model của vai trò hoặc lượt đã nâng cấp."""
    agent = agent_for(role)
    if not agent or _escalated.get():
        return None
    return (getattr(settings, 'AGENT_MODELS', None) or {}).get(agent)


@contextmanager
def acting(agent):
    token = active.set(agent)
    try:
        yield
    finally:
        active.reset(token)


@contextmanager
def escalate():
    token = _escalated.set(True)
    try:
        yield
    finally:
        _escalated.reset(token)
