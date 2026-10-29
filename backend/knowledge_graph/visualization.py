"""Read-only, owner-scoped personal knowledge map for the UI.

The payload mirrors how a coach organizes what they know: a profile, a few
derived insights, and a disclosure tree (Bạn → hubs → records → details) that
the client reveals one click at a time, plus conversation intents and a
timeline. Every record comes from the projection; nothing here is model text.

With a local-day window the map shows only the records of those days, at most
WINDOW_PER_KIND of each kind, with totals and per-day activity so the client can
draw a time scrubber and say what was left out.
"""
import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, time, timedelta, timezone

from .driver import create_driver, value
from .intents import hub as intent_hub, label as intent_label
from .model import DISCIPLINES, FOCUS, LEVELS, LOCAL, parse_time

log = logging.getLogger(__name__)

QUERY = """
MATCH (s:KGState {key:'main'}) WHERE s.ready=true
OPTIONAL MATCH (m:KGEntity {key:$model_key})
CALL () {
  MATCH (n:KGEntity {owner_id:$owner})
  WHERE n.kind IN ['Goal','BodyMetric','Meal','Training'] AND coalesce(n.deleted,false)=false
    AND n.fact_json IS NOT NULL AND (NOT n:Goal OR n.status='IN_PROGRESS')
    AND (n:Goal OR (coalesce(n.business_at, n.source_at) >= $business
                    AND ($until IS NULL OR coalesce(n.business_at, n.source_at) < $until)))
  WITH n ORDER BY coalesce(n.business_at, n.source_at) DESC
  WITH n.kind AS kind, collect(n) AS found
  WITH collect({kind:kind, total:size(found)}) AS totals, collect(found[0..$per_kind]) AS kept
  RETURN totals, [n IN reduce(rows = [], part IN kept | rows + part) | {key:n.key, fact:n.fact_json}] AS records
}
CALL () {
  MATCH (r:KGEntity {owner_id:$owner, kind:'Run'})
  WHERE r.deleted=false AND r.intent IS NOT NULL AND r.business_at >= $memory
    AND ($until IS NULL OR r.business_at < $until)
    AND r.session_id IN $sessions AND r.session_generation = $generations[r.session_id]
  WITH r ORDER BY r.business_at DESC LIMIT $run_limit
  OPTIONAL MATCH (r)-[:ABOUT]->(x:KGEntity)
  WITH r, collect(x.key) AS about
  RETURN collect({key:r.key, fact:r.fact_json, about:about}) AS runs
}
CALL () {
  MATCH (:KGEntity {key:$user_key})-[rel:FREQUENTLY_EATS|PRACTICES]->(x:KGEntity)
  WHERE coalesce(x.deleted,false)=false
  RETURN collect({type:type(rel), key:x.key, count:coalesce(rel.count, rel.sessions)}) AS habits
}
CALL () {
  // When over the whole retained history, behind the same session gate as runs.
  MATCH (n:KGEntity {owner_id:$owner})
  WHERE $density AND n.kind IN ['BodyMetric','Meal','Training','Run'] AND coalesce(n.deleted,false)=false
    AND n.fact_json IS NOT NULL AND coalesce(n.business_at, n.source_at) >= $retained
    AND (n.kind <> 'Run' OR (n.intent IS NOT NULL AND n.business_at >= $remembered
                             AND n.session_id IN $sessions AND n.session_generation = $generations[n.session_id]))
  RETURN collect([n.kind, coalesce(n.business_at, n.source_at)]) AS moments
}
RETURN s.projection_lag_ms AS lag_ms, records, totals, runs, habits, moments,
       CASE WHEN m IS NULL OR coalesce(m.deleted,false) THEN null ELSE m.model_json END AS model
"""
DEFAULT_PER_KIND = 14
WINDOW_PER_KIND = 40
WINDOW_KINDS = {'BodyMetric': 'body', 'Meal': 'nutrition', 'Training': 'training', 'Run': 'conversation'}
HUBS = {'goal': 'Mục tiêu', 'body': 'Cơ thể', 'nutrition': 'Dinh dưỡng', 'training': 'Tập luyện', 'conversation': 'Hội thoại'}
STATUS = {'completed': 'Hoàn tất', 'needs_input': 'Chờ bổ sung', 'pending_confirmation': 'Chờ xác nhận', 'failed': 'Lỗi'}
DOMAINS = {'meals': 'Bữa ăn', 'foods': 'Thực phẩm', 'metrics': 'Số đo', 'goals': 'Mục tiêu', 'progress': 'Tiến độ',
           'trainings': 'Buổi tập', 'exercises': 'Bài tập', 'coaching': 'Huấn luyện', 'training_plans': 'Kế hoạch tập',
           'profile': 'Hồ sơ'}
EMPTY = {'status': 'unavailable', 'lag_ms': None, 'mode': None, 'profile': None, 'insights': [], 'intents': [],
         'nodes': [], 'edges': [], 'timeline': []}


def _n(number, unit=''):
    if number is None:
        return None
    text = f'{round(float(number), 1):g}'
    return f'{text} {unit}'.strip()


def _local(value, pattern='%d/%m %H:%M'):
    moment = parse_time(value)
    return moment.astimezone(LOCAL).strftime(pattern) if moment else None


def _date(iso):
    return f'{iso[8:10]}/{iso[5:7]}/{iso[:4]}' if iso else None


def _details(*pairs):
    return [{'label': label, 'value': str(value)} for label, value in pairs if value not in (None, '', [])]


class MapBuilder:
    def __init__(self):
        self.nodes, self.edges, self.timeline = {}, [], []

    def node(self, id, kind, label, parent=None, hub=None, **extra):
        if id in self.nodes:
            return self.nodes[id]
        depth = self.nodes[parent]['depth'] + 1 if parent in self.nodes else 0
        self.nodes[id] = {'id': id, 'kind': kind, 'label': str(label)[:90], 'parent': parent, 'hub': hub, 'depth': depth,
                          'summary': None, 'details': [], 'at': None, 'count': None, **extra}
        if parent:
            self.edges.append({'source': parent, 'target': id, 'kind': 'tree', 'label': None})
        return self.nodes[id]

    def link(self, source, target, label):
        if source in self.nodes and target in self.nodes and source != target:
            self.edges.append({'source': source, 'target': target, 'kind': 'link', 'label': label})

    def event(self, id, hub, at, title, subtitle, node):
        if at:
            self.timeline.append({'id': id, 'hub': hub, 'at': at, 'title': title, 'subtitle': subtitle, 'node_id': node})


def _profile(model):
    profile = (model or {}).get('profile') or {}
    training = profile.get('training') or {}
    if not profile:
        return None
    return {'age': profile.get('age'), 'height_cm': profile.get('height_cm'), 'weight_kg': profile.get('weight_kg'),
            'bmi': profile.get('bmi'),
            'experience': LEVELS.get(training.get('experience_level'), training.get('experience_level')),
            'focus': FOCUS.get(training.get('primary_focus'), training.get('primary_focus')),
            'available_days': training.get('available_days'), 'session_minutes': training.get('session_minutes'),
            'equipment': training.get('equipment') or []}


def _insights(model, intents):
    model, insights = model or {}, []
    goal, body = model.get('goal') or {}, model.get('body') or {}
    nutrition, training = model.get('nutrition') or {}, model.get('training') or {}
    if goal:
        progress = goal.get('progress_pct')
        insights.append({'id': 'goal', 'hub': 'goal', 'title': 'Mục tiêu', 'value': f'{progress}%' if progress is not None else '—',
                         'caption': goal.get('title'), 'progress': progress / 100 if progress is not None else None,
                         'detail': ' · '.join(filter(None, [f"Còn {_n(goal['remaining_kg'], 'kg')}" if goal.get('remaining_kg') is not None else None,
                                                            f"{goal['days_left']} ngày" if goal.get('days_left') is not None else None])),
                         'tone': 'positive' if goal.get('on_track') or goal.get('achieved') else 'warning' if goal.get('on_track') is False else 'neutral'})
    if body:
        change = max(body.get('changes') or [], key=lambda c: c['days'], default=None)
        insights.append({'id': 'weight', 'hub': 'body', 'title': 'Cân nặng', 'value': _n(body['latest']['weight_kg'], 'kg'),
                         'caption': f"{change['delta_kg']:+g} kg so với {_date(change['since'])}" if change else f"Đo {_date(body['latest']['date'])}",
                         'detail': f"Xu hướng {body['trend']}", 'series': [point['weight_kg'] for point in body.get('series', [])],
                         'tone': 'neutral'})
    if nutrition:
        today = nutrition.get('today') or {}
        insights.append({'id': 'nutrition', 'hub': 'nutrition', 'title': 'Dinh dưỡng',
                         'value': f"{nutrition['avg_kcal']} kcal" if nutrition.get('avg_kcal') is not None else '—',
                         'caption': f"TB/ngày · {nutrition['logged_days']}/{nutrition['window_days']} ngày có ghi",
                         'detail': f"Hôm nay {_n(today.get('kcal'), 'kcal')} · {today.get('meals')} bữa" if today else 'Hôm nay chưa ghi bữa nào',
                         'bars': [day['kcal'] for day in nutrition.get('daily', [])], 'tone': 'neutral'})
    if training:
        planned = training.get('planned_days')
        insights.append({'id': 'training', 'hub': 'training', 'title': 'Tập luyện',
                         'value': f"{training['sessions_week']}/{planned}" if planned else str(training['sessions_week']),
                         'caption': 'buổi tuần này', 'progress': min(1, training['sessions_week'] / planned) if planned else None,
                         'detail': f"{training['sessions_28d']} buổi / 28 ngày · tải 7 ngày {training['load_7d']}",
                         'bars': [week['sessions'] for week in training.get('weeks', [])], 'tone': 'neutral'})
    if intents:
        top = intents[0]
        insights.append({'id': 'conversation', 'hub': 'conversation', 'title': 'Hay hỏi', 'value': top['label'],
                         'caption': f"{top['count']} lượt / 30 ngày", 'detail': f"{sum(i['count'] for i in intents)} lượt hội thoại",
                         'tone': 'neutral'})
    return insights


def _goal(builder, records, model):
    derived = (model or {}).get('goal') or {}
    for record in records:
        data = record['data']
        node = builder.node(record['key'], 'Goal', data.get('title') or 'Mục tiêu', 'hub:goal', 'goal')
        same = derived.get('title') == data.get('title')
        node['summary'] = f"Hạn {_date(data.get('target_date'))}" if data.get('target_date') else None
        node['details'] = _details(
            ('Mô tả', data.get('description')), ('Bắt đầu', _date(data.get('start_date'))), ('Hạn', _date(data.get('target_date'))),
            ('Cân nặng đích', _n(derived.get('target_weight_kg'), 'kg') if same else _n(data.get('weight_kg_target'), 'kg')),
            ('Xuất phát', _n(derived.get('start_weight_kg'), 'kg') if same else None),
            ('Hiện tại', _n(derived.get('current_weight_kg'), 'kg') if same else None),
            ('Còn lại', _n(derived.get('remaining_kg'), 'kg') if same else None),
            ('Tiến độ', f"{derived['progress_pct']}%" if same and derived.get('progress_pct') is not None else None),
            ('Còn', f"{derived['days_left']} ngày" if same and derived.get('days_left') is not None else None),
            ('Nhịp cần', _n(derived.get('required_kg_per_week'), 'kg/tuần') if same else None),
            ('Nhịp thực tế', _n(derived.get('actual_kg_per_week'), 'kg/tuần') if same else None),
            ('Đánh giá', ('Đúng tiến độ' if derived['on_track'] else 'Chậm hơn kế hoạch') if same and derived.get('on_track') is not None else None))
        builder.event(record['key'], 'goal', data.get('start_date'), f"Bắt đầu mục tiêu: {data.get('title')}",
                      f"Hạn {_date(data.get('target_date'))}" if data.get('target_date') else None, record['key'])


def _body(builder, records):
    for record in records:
        data = record['data']
        weight, height = data.get('weight_kg'), data.get('height_cm')
        at = _local(data.get('recorded_at'), '%d/%m/%Y')
        node = builder.node(record['key'], 'BodyMetric', f"{_n(weight, 'kg') or 'Số đo'} · {at}", 'hub:body', 'body',
                            at=data.get('recorded_at'))
        node['details'] = _details(('Cân nặng', _n(weight, 'kg')), ('Chiều cao', _n(height, 'cm')),
                                   ('BMI', _n(weight / (height / 100) ** 2) if weight and height else None),
                                   ('Mỡ cơ thể', _n(data.get('body_fat_pct'), '%')), ('Khối cơ', _n(data.get('muscle_mass_kg'), 'kg')),
                                   ('Thời điểm', _local(data.get('recorded_at'), '%d/%m/%Y %H:%M')))
        builder.event(record['key'], 'body', data.get('recorded_at'), f"Cân nặng {_n(weight, 'kg')}" if weight else 'Số đo cơ thể',
                      f"Chiều cao {_n(height, 'cm')}" if height else None, record['key'])


def _nutrition(builder, records, model, habits):
    foods = {food.get('key'): food for food in ((model or {}).get('nutrition') or {}).get('top_foods', []) if food.get('key')}
    favourite_keys = [habit['key'] for habit in habits if habit['type'] == 'FREQUENTLY_EATS'] or list(foods)
    if favourite_keys:
        builder.node('grp:foods', 'Group', 'Món hay ăn', 'hub:nutrition', 'nutrition', count=len(favourite_keys))
    for key in favourite_keys:
        food = foods.get(key) or {}
        node = builder.node(key, 'Food', food.get('name') or 'Thực phẩm', 'grp:foods', 'nutrition', count=food.get('count'))
        node['summary'] = f"{food['count']} lần" if food.get('count') else None
        node['details'] = _details(('Số lần ăn (90 ngày)', food.get('count')), ('Gần nhất', _date(food.get('last_date'))))
    if records:
        builder.node('grp:meals', 'Group', 'Bữa ăn gần đây', 'hub:nutrition', 'nutrition', count=len(records))
    for record in records:
        data = record['data']
        items = data.get('items') or []
        names = ', '.join((item.get('food_snapshot') or {}).get('name_vi') or 'Món' for item in items)
        node = builder.node(record['key'], 'Meal', f"{data.get('name') or 'Bữa ăn'} · {_local(data.get('consumed_at'))}",
                            'grp:meals', 'nutrition', at=data.get('consumed_at'), count=len(items))
        node['summary'] = names or None
        node['details'] = _details(('Thời điểm', _local(data.get('consumed_at'), '%d/%m/%Y %H:%M')),
                                   ('Năng lượng', _n(data.get('energy_kcal'), 'kcal')), ('Protein', _n(data.get('protein_g'), 'g')),
                                   ('Carb', _n(data.get('carbohydrate_g'), 'g')), ('Chất béo', _n(data.get('fat_g'), 'g')),
                                   ('Chất xơ', _n(data.get('fiber_g'), 'g')),
                                   ('Ghi chú', 'Thiếu dữ liệu dinh dưỡng' if data.get('nutrition_incomplete') else None))
        for index, item in enumerate(items):
            snapshot = item.get('food_snapshot') or {}
            unit = {'G': 'g', 'ML': 'ml', 'SERVING': ' phần'}.get(item.get('unit'), '')
            portion = builder.node(f"{record['key']}:item:{index}", 'MealItem',
                                   f"{snapshot.get('name_vi') or 'Món'} {_n(item.get('quantity'))}{unit}".strip(),
                                   record['key'], 'nutrition')
            portion['details'] = _details(('Năng lượng', _n(item.get('energy_kcal'), 'kcal')), ('Protein', _n(item.get('protein_g'), 'g')),
                                          ('Carb', _n(item.get('carbohydrate_g'), 'g')), ('Chất béo', _n(item.get('fat_g'), 'g')))
            if item.get('food_id'):
                builder.link(portion['id'], 'backend:Food:' + str(item['food_id']), 'là món')
        builder.event(record['key'], 'nutrition', data.get('consumed_at'), data.get('name') or 'Bữa ăn',
                      ' · '.join(filter(None, [names, _n(data.get('energy_kcal'), 'kcal')])), record['key'])


def _training(builder, records, model):
    exercises = ((model or {}).get('training') or {}).get('exercises') or []
    if exercises:
        builder.node('grp:exercises', 'Group', 'Bài tập chính', 'hub:training', 'training', count=len(exercises))
    for exercise in exercises:
        key = exercise.get('key') or 'exercise:' + exercise['name']
        node = builder.node(key, 'Exercise', exercise['name'], 'grp:exercises', 'training', count=exercise.get('sessions'))
        node['summary'] = ' · '.join(filter(None, [f"{exercise['sessions']} buổi",
                                                   f"e1RM {_n(exercise['best_e1rm_kg'], 'kg')}" if exercise.get('best_e1rm_kg') else None,
                                                   _n(exercise.get('distance_km'), 'km')]))
        pace = exercise.get('pace_s_per_km')
        node['details'] = _details(('Số buổi', exercise.get('sessions')), ('Gần nhất', _date(exercise.get('last_date'))),
                                   ('e1RM đầu kỳ', _n(exercise.get('first_e1rm_kg'), 'kg')), ('e1RM tốt nhất', _n(exercise.get('best_e1rm_kg'), 'kg')),
                                   ('Tổng quãng đường', _n(exercise.get('distance_km'), 'km')), ('Dài nhất', _n(exercise.get('longest_km'), 'km')),
                                   ('Pace TB', f'{pace // 60}:{pace % 60:02d}/km' if pace else None))
    if records:
        builder.node('grp:sessions', 'Group', 'Buổi tập gần đây', 'hub:training', 'training', count=len(records))
    for record in records:
        data = record['data']
        items = data.get('items') or []
        minutes = round(data['duration_seconds'] / 60) if data.get('duration_seconds') else None
        node = builder.node(record['key'], 'Training', f"{data.get('name') or 'Buổi tập'} · {_local(data.get('started_at'))}",
                            'grp:sessions', 'training', at=data.get('started_at'), count=len(items))
        node['summary'] = DISCIPLINES.get(data.get('discipline'), data.get('discipline'))
        node['details'] = _details(('Thời điểm', _local(data.get('started_at'), '%d/%m/%Y %H:%M')),
                                   ('Nhóm', DISCIPLINES.get(data.get('discipline'), data.get('discipline'))),
                                   ('Thời lượng', f'{minutes} phút' if minutes else None), ('RPE buổi', _n(data.get('session_rpe'))),
                                   ('Tải (sRPE)', _n(data.get('training_load'))), ('Năng lượng', _n(data.get('energy_kcal'), 'kcal')))
        for index, item in enumerate(items):
            exercise = item.get('exercise') or {}
            entry = builder.node(f"{record['key']}:item:{index}", 'TrainingItem', exercise.get('name_vi') or 'Bài tập',
                                 record['key'], 'training')
            entry['details'] = _details(('Số hiệp nặng', item.get('hard_sets')), ('Volume', _n(item.get('volume_kg'), 'kg')),
                                        ('e1RM', _n(item.get('best_e1rm_kg'), 'kg')),
                                        ('Quãng đường', _n(item['distance_meters'] / 1000, 'km') if item.get('distance_meters') else None),
                                        ('Thời lượng', f"{round(item['duration_seconds'] / 60)} phút" if item.get('duration_seconds') else None))
            if item.get('exercise_id'):
                builder.link(entry['id'], 'backend:Exercise:' + str(item['exercise_id']), 'bài tập')
        builder.event(record['key'], 'training', data.get('started_at'), data.get('name') or 'Buổi tập',
                      ' · '.join(filter(None, [DISCIPLINES.get(data.get('discipline'), data.get('discipline')),
                                               f'{minutes} phút' if minutes else None,
                                               ', '.join((item.get('exercise') or {}).get('name_vi') or '' for item in items[:3])])),
                      record['key'])


def _conversation(builder, runs):
    counts = Counter(run['data'].get('intent') for run in runs)
    intents = []
    for intent, count in counts.most_common():
        latest = max((run['data'].get('occurred_at') for run in runs if run['data'].get('intent') == intent), default=None)
        intents.append({'intent': intent, 'label': intent_label(intent), 'hub': intent_hub(intent), 'count': count,
                        'last_at': latest, 'node_id': 'intent:' + intent})
        node = builder.node('intent:' + intent, 'Intent', intent_label(intent), 'hub:conversation', 'conversation', count=count)
        node['summary'] = f'{count} lượt'
        node['details'] = _details(('Số lượt (30 ngày)', count), ('Gần nhất', _local(latest, '%d/%m/%Y %H:%M')))
    shown = Counter()
    for run in runs:
        data = run['data']
        intent = data.get('intent')
        shown[intent] += 1
        if shown[intent] > 6:
            continue
        status = STATUS.get(data.get('status'), data.get('status'))
        node = builder.node(run['key'], 'Run', f"{_local(data.get('occurred_at'))} · {status}", 'intent:' + intent,
                            'conversation', at=data.get('occurred_at'))
        node['details'] = _details(('Thời điểm', _local(data.get('occurred_at'), '%d/%m/%Y %H:%M')),
                                   ('Ý định', intent_label(intent)), ('Lĩnh vực', DOMAINS.get(data.get('domain'), data.get('domain'))),
                                   ('Trạng thái', status), ('Công cụ', ', '.join(data.get('tools') or [])))
        builder.event(run['key'], 'conversation', data.get('occurred_at'), intent_label(intent),
                      ' · '.join(filter(None, [status, DOMAINS.get(data.get('domain'))])), run['key'])
    return intents


def window_bounds(settings, now, start=None, end=None):
    """Clamp an inclusive local-day window to the retained history and turn it into UTC bounds."""
    retained = now - timedelta(days=value(settings, 'KG_BUSINESS_RETENTION_DAYS', 90))
    remembered = now - timedelta(days=value(settings, 'KG_MEMORY_RETENTION_DAYS', 30))
    floor, today = retained.astimezone(LOCAL).date(), now.astimezone(LOCAL).date()
    end = max(floor, min(end or today, today))
    start = max(floor, min(start or end - timedelta(days=14), end))
    since = datetime.combine(start, time.min, LOCAL).astimezone(timezone.utc)
    until = datetime.combine(end + timedelta(days=1), time.min, LOCAL).astimezone(timezone.utc)
    return {'start': start, 'end': end, 'floor': floor, 'today': today, 'retained': retained, 'remembered': remembered,
            'business': max(since, retained), 'memory': max(since, remembered), 'until': until}


def density(moments):
    """Activity per local day and hub; days without activity are left out."""
    days = {}
    for kind, at in moments:
        moment, hub = parse_time(at), WINDOW_KINDS.get(kind)
        if moment and hub:
            counts = days.setdefault(moment.astimezone(LOCAL).date().isoformat(), {})
            counts[hub] = counts.get(hub, 0) + 1
    return dict(sorted(days.items()))


def window_meta(bounds, totals=(), moments=()):
    return {'start': bounds['start'].isoformat(), 'end': bounds['end'].isoformat(),
            'min': bounds['floor'].isoformat(), 'max': bounds['today'].isoformat(), 'limit': WINDOW_PER_KIND,
            'totals': {row['kind']: row['total'] for row in totals if row['kind'] in WINDOW_KINDS},
            'density': density(moments)}


def build_map(model, records, runs, habits):
    builder = MapBuilder()
    by_kind = {'Goal': [], 'BodyMetric': [], 'Meal': [], 'Training': []}
    for record in records:
        fact = json.loads(record['fact'])
        by_kind.setdefault(fact.get('kind'), []).append({'key': record['key'], 'data': fact.get('data') or {}})
    runs = [{'key': run['key'], 'about': run.get('about') or [], 'data': (json.loads(run['fact']) or {}).get('data') or {}}
            for run in runs if run.get('fact')]
    profile = _profile(model)
    root = builder.node('me', 'User', 'Bạn')
    if profile:
        root['summary'] = ' · '.join(filter(None, [f"{profile['age']} tuổi" if profile.get('age') else None,
                                                   _n(profile.get('height_cm'), 'cm'), f"BMI {_n(profile['bmi'])}" if profile.get('bmi') else None]))
        root['details'] = _details(('Tuổi', profile.get('age')), ('Chiều cao', _n(profile.get('height_cm'), 'cm')),
                                   ('Cân nặng', _n(profile.get('weight_kg'), 'kg')), ('BMI', _n(profile.get('bmi'))),
                                   ('Trình độ', profile.get('experience')), ('Trọng tâm', profile.get('focus')),
                                   ('Lịch tập', f"{profile['available_days']} buổi/tuần" if profile.get('available_days') else None),
                                   ('Mỗi buổi', f"{profile['session_minutes']} phút" if profile.get('session_minutes') else None),
                                   ('Dụng cụ', ', '.join(profile.get('equipment') or [])))
    for hub, title in HUBS.items():
        builder.node('hub:' + hub, 'Hub', title, 'me', hub)
    _goal(builder, by_kind['Goal'], model)
    _body(builder, sorted(by_kind['BodyMetric'], key=lambda r: r['data'].get('recorded_at') or '', reverse=True))
    _nutrition(builder, sorted(by_kind['Meal'], key=lambda r: r['data'].get('consumed_at') or '', reverse=True), model, habits)
    _training(builder, sorted(by_kind['Training'], key=lambda r: r['data'].get('started_at') or '', reverse=True), model)
    intents = _conversation(builder, sorted(runs, key=lambda r: r['data'].get('occurred_at') or '', reverse=True))
    for run in runs:
        for key in run['about']:
            builder.link(run['key'], key, 'liên quan')
    for node in builder.nodes.values():
        node['children'] = sum(1 for edge in builder.edges if edge['kind'] == 'tree' and edge['source'] == node['id'])
    insights = _insights(model, intents)
    by_hub = {item['hub']: item for item in insights}
    for hub, item in by_hub.items():
        summary = {'goal': item.get('detail'), 'body': item.get('value'), 'nutrition': f"TB {item.get('value')}/ngày",
                   'training': f"{item.get('value')} {item.get('caption')}", 'conversation': item.get('detail')}[hub]
        builder.nodes['hub:' + hub]['summary'] = summary
    timeline = sorted(builder.timeline, key=lambda event: str(parse_time(event['at']) or event['at']), reverse=True)[:80]
    return {'profile': profile, 'insights': insights, 'intents': intents,
            'nodes': list(builder.nodes.values()), 'edges': builder.edges, 'timeline': timeline}


async def personal_graph(service, user_id, start=None, end=None):
    settings = getattr(service, 'settings', None)
    now = datetime.now(timezone.utc)
    windowed = start is not None or end is not None
    bounds = window_bounds(settings, now, start, end)
    empty = {**EMPTY, 'mode': value(settings, 'KG_MODE', 'off')}
    if windowed:
        empty['window'] = window_meta(bounds)
    try:
        async with asyncio.timeout(3):
            gate = await service.store.kg_retrieval_gate(user_id)
            if gate.get('blocked'):
                return {**empty, 'status': 'blocked'}
            generations = {str(k): int(v) for k, v in gate.get('session_generations', {}).items()
                           if str(k) not in set(gate.get('deleted_session_ids', []))}
            if service.driver is None:
                service.driver = create_driver(service.settings)
            async with service.driver.session(database=value(service.settings, 'NEO4J_DATABASE', 'neo4j')) as session:
                record = await (await session.run(
                    QUERY, owner=user_id, user_key='backend:User:' + user_id, model_key='model:' + user_id,
                    sessions=list(generations), generations=generations, run_limit=60,
                    per_kind=WINDOW_PER_KIND if windowed else DEFAULT_PER_KIND, density=windowed,
                    business=(bounds['business'] if windowed else bounds['retained']).isoformat(),
                    memory=(bounds['memory'] if windowed else bounds['remembered']).isoformat(),
                    until=bounds['until'].isoformat() if windowed else None,
                    retained=bounds['retained'].isoformat(), remembered=bounds['remembered'].isoformat())).single()
            if record is None:
                return {**empty, 'status': 'warming'}
            model = json.loads(record['model']) if record['model'] else None
            payload = build_map(model, record['records'], record['runs'], record['habits'])
            has_data = any(node['kind'] not in {'User', 'Hub'} for node in payload['nodes'])
            if windowed:
                payload['window'] = window_meta(bounds, record['totals'], record['moments'])
            return {**empty, **payload, 'status': 'ok' if has_data else 'empty', 'lag_ms': record['lag_ms'],
                    'model_at': (model or {}).get('computed_at'), 'generated_at': now.isoformat()}
    except Exception as exc:
        log.warning('kg_visualization_failed error_type=%s', type(exc).__name__)
        return empty
