"""Conversation intent taxonomy shared by the agent journal and the graph.

Intents are derived from structured routing facts (domain, write, research),
never from message, reply or free-form model text, so they are safe to keep
as long-lived personal knowledge.
"""

# name: (Vietnamese label, hub)
INTENTS = {
    'LOG_MEAL': ('Ghi bữa ăn', 'nutrition'),
    'REVIEW_NUTRITION': ('Xem dinh dưỡng', 'nutrition'),
    'FOOD_KNOWLEDGE': ('Hỏi về thực phẩm', 'nutrition'),
    'LOG_TRAINING': ('Ghi buổi tập', 'training'),
    'REVIEW_TRAINING': ('Xem lịch sử tập', 'training'),
    'COACHING': ('Phân tích tập luyện', 'training'),
    'TRAINING_PLAN': ('Kế hoạch tập', 'training'),
    'EXERCISE_KNOWLEDGE': ('Hỏi về bài tập', 'training'),
    'LOG_METRIC': ('Cập nhật số đo', 'body'),
    'REVIEW_BODY': ('Xem số đo', 'body'),
    'SET_GOAL': ('Đặt mục tiêu', 'goal'),
    'REVIEW_GOAL': ('Xem mục tiêu', 'goal'),
    'PROGRESS': ('Xem tiến độ', 'goal'),
    'PROFILE': ('Hồ sơ cá nhân', 'profile'),
    'KNOWLEDGE': ('Hỏi kiến thức', 'knowledge'),
    'CHAT': ('Trò chuyện', 'chat'),
}
# domain: (intent when the turn wrote or requested a write, intent otherwise)
DOMAIN_INTENTS = {
    'meals': ('LOG_MEAL', 'REVIEW_NUTRITION'), 'foods': ('FOOD_KNOWLEDGE', 'FOOD_KNOWLEDGE'),
    'trainings': ('LOG_TRAINING', 'REVIEW_TRAINING'), 'exercises': ('EXERCISE_KNOWLEDGE', 'EXERCISE_KNOWLEDGE'),
    'coaching': ('COACHING', 'COACHING'), 'training_plans': ('TRAINING_PLAN', 'TRAINING_PLAN'),
    'metrics': ('LOG_METRIC', 'REVIEW_BODY'), 'goals': ('SET_GOAL', 'REVIEW_GOAL'),
    'progress': ('PROGRESS', 'PROGRESS'), 'profile': ('PROFILE', 'PROFILE'),
}
# Router labels requested by the research v2 prompt.
MODEL_INTENTS = {
    'LOG_FOOD': 'LOG_MEAL', 'LOG_EXERCISE': 'LOG_TRAINING', 'FOOD_KNOWLEDGE_QA': 'FOOD_KNOWLEDGE',
    'SPORTS_KNOWLEDGE_QA': 'EXERCISE_KNOWLEDGE', 'EXERCISE_TECHNIQUE_QA': 'EXERCISE_KNOWLEDGE',
    'TRAINING_PLAN': 'TRAINING_PLAN', 'DEEP_RESEARCH': 'KNOWLEDGE', 'GENERAL_CHAT': 'CHAT',
}
TRAINING_DOMAINS = {'trainings', 'exercises', 'coaching'}


def classify(domain=None, model_intent=None, *, wrote=False, researched=False):
    mapped = MODEL_INTENTS.get(str(model_intent or '').strip().upper())
    if researched and not wrote:
        # A public-knowledge answer about a personal domain is still a question.
        if domain in {'meals', 'foods'}:
            return 'FOOD_KNOWLEDGE'
        if domain in TRAINING_DOMAINS:
            return 'EXERCISE_KNOWLEDGE'
        if domain not in DOMAIN_INTENTS:
            return mapped or 'KNOWLEDGE'
    if domain in DOMAIN_INTENTS:
        write, read = DOMAIN_INTENTS[domain]
        return write if wrote else read
    return mapped or 'CHAT'


def label(intent):
    return INTENTS.get(intent, INTENTS['CHAT'])[0]


def hub(intent):
    return INTENTS.get(intent, INTENTS['CHAT'])[1]
