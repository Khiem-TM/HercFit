"""Derived personal knowledge: what an attentive coach remembers about a user.

Pure functions over projected facts, so the worker can rebuild a model at any
time and tests can check every number. Dates are local (Asia/Ho_Chi_Minh).
Only backend business facts feed the stored model; conversation statistics are
aggregated at read time behind the SQL session gate.
"""
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .intents import label as intent_label

LOCAL = ZoneInfo('Asia/Ho_Chi_Minh')
MODEL_VERSION = 1
LEVELS = {'BEGINNER': 'mới bắt đầu', 'INTERMEDIATE': 'trung cấp', 'ADVANCED': 'nâng cao'}
FOCUS = {'STRENGTH': 'sức mạnh', 'RUNNING': 'chạy bộ', 'HYBRID': 'kết hợp sức mạnh và chạy'}
DISCIPLINES = {'STRENGTH': 'sức mạnh', 'ENDURANCE': 'sức bền', 'SPORT': 'thể thao', 'MIXED': 'kết hợp'}
PROFILE_FIELDS = ('experience_level', 'primary_focus', 'available_days', 'session_minutes', 'equipment')


def parse_time(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def number(value):
    try:
        return float(value) if value is not None and value != '' else None
    except (TypeError, ValueError):
        return None


def local_day(moment):
    return moment.astimezone(LOCAL).date()


def _round(value, digits=1):
    return None if value is None else round(value, digits)


def _metrics(facts):
    rows = []
    for fact in facts:
        data = fact.get('data') or {}
        at = parse_time(data.get('recorded_at')) or parse_time(fact.get('source_at'))
        weight, height = number(data.get('weight_kg')), number(data.get('height_cm'))
        if at and (weight or height):
            rows.append({'at': at, 'weight_kg': weight, 'height_cm': height, 'body_fat_pct': number(data.get('body_fat_pct'))})
    return sorted(rows, key=lambda row: row['at'])


def _profile(user, metrics):
    height = next((m['height_cm'] for m in reversed(metrics) if m['height_cm']), None)
    weight = next((m['weight_kg'] for m in reversed(metrics) if m['weight_kg']), None)
    training = {key: value for key, value in (user.get('training_profile') or {}).items()
                if key in PROFILE_FIELDS and value not in (None, '', [])}
    profile = {'age': user.get('age'), 'height_cm': height, 'weight_kg': weight,
               'bmi': _round(weight / (height / 100) ** 2) if weight and height else None,
               'training': training or None}
    return profile if any(value is not None for value in profile.values()) else None


def _body(metrics):
    weights = [m for m in metrics if m['weight_kg'] is not None]
    if not weights:
        return None
    latest = weights[-1]
    changes = []
    for window in (7, 30):
        # The most recent measurement at least ~80% of the window before the latest one.
        base = next((m for m in reversed(weights[:-1]) if (latest['at'] - m['at']).days >= window * .8), None)
        if base and not any(change['since'] == local_day(base['at']).isoformat() for change in changes):
            changes.append({'window': window, 'delta_kg': _round(latest['weight_kg'] - base['weight_kg']),
                            'since': local_day(base['at']).isoformat(),
                            'days': round((latest['at'] - base['at']).total_seconds() / 86400)})
    longest = max(changes, key=lambda change: change['days'], default=None)
    rate = round(longest['delta_kg'] / longest['days'] * 7, 2) if longest and longest['days'] else None
    # Least-squares slope over the last 30 days: robust to day-to-day water noise and,
    # unlike a moving average, without lag when weigh-ins are sparse.
    recent = [m for m in weights if (latest['at'] - m['at']).days <= 30]
    span = (recent[-1]['at'] - recent[0]['at']).total_seconds() / 86400 if len(recent) >= 2 else 0
    if len(recent) >= 3 and span >= 7:
        xs = [(m['at'] - recent[0]['at']).total_seconds() / 86400 for m in recent]
        ys = [m['weight_kg'] for m in recent]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        denominator = sum((x - mx) ** 2 for x in xs)
        if denominator:
            rate = round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denominator * 7, 2)
    delta = longest['delta_kg'] if longest else 0
    return {'latest': {'weight_kg': latest['weight_kg'], 'date': local_day(latest['at']).isoformat()},
            'changes': changes, 'rate_kg_per_week': rate,
            'trend': 'giảm' if delta <= -.3 else 'tăng' if delta >= .3 else 'ổn định',
            'series': [{'date': local_day(m['at']).isoformat(), 'weight_kg': m['weight_kg']} for m in weights[-12:]]}


def _target_from_text(*texts):
    for text in texts:
        found = re.findall(r'(\d+(?:[.,]\d+)?)\s*kg', str(text or '').lower())
        if found:
            return float(found[-1].replace(',', '.'))
    return None


def _goal(facts, metrics, body, today):
    active = [fact.get('data') or {} for fact in facts if str((fact.get('data') or {}).get('status', '')).upper() == 'IN_PROGRESS']
    if not active:
        return None
    goal = max(active, key=lambda data: str(data.get('start_date') or ''))
    start, end = parse_date(goal.get('start_date')), parse_date(goal.get('target_date'))
    target, source = number(goal.get('weight_kg_target')), 'goal'
    if target is None:
        target, source = _target_from_text(goal.get('title'), goal.get('description')), 'title'
    result = {'title': goal.get('title'), 'goal_types': goal.get('goal_types') or [], 'start_date': goal.get('start_date'),
              'target_date': goal.get('target_date'), 'target_weight_kg': target, 'target_source': source if target is not None else None}
    if end:
        result['days_left'] = (end - today).days
        if start and end > start:
            result['time_pct'] = max(0, min(100, round(100 * (today - start).days / (end - start).days)))
    weights = [m for m in metrics if m['weight_kg'] is not None]
    if target is None or not weights:
        return result
    cutoff = datetime.combine(start + timedelta(days=3), datetime.max.time(), LOCAL) if start else None
    baseline = next((m for m in reversed(weights) if cutoff and m['at'] <= cutoff), weights[0])
    current = weights[-1]
    losing = target < baseline['weight_kg']
    total, done = baseline['weight_kg'] - target, baseline['weight_kg'] - current['weight_kg']
    remaining = current['weight_kg'] - target if losing else target - current['weight_kg']
    result.update(start_weight_kg=baseline['weight_kg'], start_weight_date=local_day(baseline['at']).isoformat(),
                  current_weight_kg=current['weight_kg'], direction='giảm' if losing else 'tăng',
                  remaining_kg=_round(max(0.0, remaining)), achieved=remaining <= 0,
                  progress_pct=max(0, min(100, round(100 * done / total))) if total else None)
    if result.get('days_left', 0) > 0 and remaining > 0:
        required = round((target - current['weight_kg']) / (result['days_left'] / 7), 2)
        result['required_kg_per_week'] = required
        rate = (body or {}).get('rate_kg_per_week')
        if rate is not None:
            result['actual_kg_per_week'] = rate
            result['on_track'] = rate <= required if losing else rate >= required
    return result


def _nutrition(facts, today):
    meals = []
    for fact in facts:
        data = fact.get('data') or {}
        at = parse_time(data.get('consumed_at'))
        if at:
            # Unknown stays unknown: a meal without energy data is counted, not added as 0 kcal.
            meals.append({'day': local_day(at), 'at': at, 'kcal': number(data.get('energy_kcal')),
                          'protein': number(data.get('protein_g')), 'items': data.get('items') or [],
                          'incomplete': bool(data.get('nutrition_incomplete')) or number(data.get('energy_kcal')) is None})
    if not meals:
        return None
    days = defaultdict(lambda: {'kcal': 0.0, 'protein_g': 0.0, 'meals': 0, 'unknown': 0})
    for meal in meals:
        totals = days[meal['day']]
        totals['kcal'] += meal['kcal'] or 0.0
        totals['protein_g'] += meal['protein'] or 0.0
        totals['meals'] += 1
        totals['unknown'] += meal['kcal'] is None
    # Seven complete days before today; today is still being logged.
    window = [today - timedelta(days=offset) for offset in range(1, 8)]
    logged = [day for day in window if day in days]
    foods = {}
    for meal in sorted(meals, key=lambda meal: meal['at']):
        for item in meal['items']:
            snapshot = item.get('food_snapshot') or {}
            name = snapshot.get('name_vi') or snapshot.get('name_en')
            if not name:
                continue
            food_id = item.get('food_id') or snapshot.get('id')
            entry = foods.setdefault(food_id or name, {'key': 'backend:Food:' + str(food_id) if food_id else None,
                                                       'name': name, 'count': 0})
            entry['count'] += 1
            entry['last_date'] = meal['day'].isoformat()
    def day_totals(day):
        totals = days.get(day)
        return {'date': day.isoformat(), 'kcal': _round(totals['kcal']), 'protein_g': _round(totals['protein_g']),
                'meals': totals['meals']} if totals else None
    known_days = [day for day in logged if not days[day]['unknown']]
    meals_per_day = round(sum(days[day]['meals'] for day in logged) / len(logged), 1) if logged else None
    return {'window_days': len(window), 'logged_days': len(logged), 'known_days': len(known_days),
            'avg_meals_per_logged_day': meals_per_day,
            # Fewer than two meals per logged day usually means days were not fully logged,
            # so the average understates intake; the card says so instead of hiding it.
            'likely_incomplete_logging': meals_per_day is not None and meals_per_day < 2,
            'window_start': window[-1].isoformat(), 'window_end': window[0].isoformat(),
            'avg_kcal': round(sum(days[day]['kcal'] for day in known_days) / len(known_days)) if known_days else None,
            'avg_protein_g': _round(sum(days[day]['protein_g'] for day in known_days) / len(known_days)) if known_days else None,
            'today': day_totals(today), 'yesterday': day_totals(today - timedelta(days=1)),
            # Oldest first, for charts: the seven complete days plus today.
            'daily': [{'date': day.isoformat(), 'kcal': _round(days[day]['kcal']) if day in days else None}
                      for day in [*reversed(window), today]],
            'meals_14d': sum(1 for meal in meals if meal['day'] > today - timedelta(days=14)),
            'incomplete': any(meal['incomplete'] for meal in meals),
            'top_foods': sorted(foods.values(), key=lambda food: (food['count'], food['last_date']), reverse=True)[:6]}


def _sessions(facts):
    sessions = []
    for fact in facts:
        data = fact.get('data') or {}
        at = parse_time(data.get('started_at'))
        if at:
            sessions.append({'day': local_day(at), 'at': at, 'name': data.get('name'), 'discipline': data.get('discipline'),
                             'minutes': (number(data.get('duration_seconds')) or 0) / 60,
                             'load': number(data.get('training_load')) or 0.0, 'items': data.get('items') or []})
    return sorted(sessions, key=lambda session: session['at'])


def _exercises(sessions):
    stats = {}
    for session in sessions:
        for item in session['items']:
            exercise = item.get('exercise') or {}
            name = exercise.get('name_vi') or exercise.get('name_en')
            if not name:
                continue
            exercise_id = item.get('exercise_id') or exercise.get('id')
            entry = stats.setdefault(exercise_id or name, {
                'key': 'backend:Exercise:' + str(exercise_id) if exercise_id else None, 'name': name,
                'kind': item.get('kind') or exercise.get('kind'), 'sessions': 0, 'distance_km': 0.0, 'seconds': 0.0})
            entry['sessions'] += 1
            entry['last_date'] = session['day'].isoformat()
            e1rm = number(item.get('best_e1rm_kg'))
            if e1rm:
                entry.setdefault('first_e1rm_kg', _round(e1rm))
                entry['best_e1rm_kg'] = max(entry.get('best_e1rm_kg') or 0, _round(e1rm))
                entry['last_e1rm_kg'] = _round(e1rm)
            distance = number(item.get('distance_meters'))
            if distance:
                entry['distance_km'] += distance / 1000
                entry['longest_km'] = max(entry.get('longest_km') or 0, _round(distance / 1000))
                entry['seconds'] += number(item.get('duration_seconds')) or 0
    result = []
    for entry in stats.values():
        if entry['distance_km'] and entry['seconds']:
            entry['pace_s_per_km'] = round(entry['seconds'] / entry['distance_km'])
        entry['distance_km'] = _round(entry['distance_km']) or None
        entry.pop('seconds')
        result.append({key: value for key, value in entry.items() if value is not None})
    return sorted(result, key=lambda entry: (entry['sessions'], entry['last_date']), reverse=True)[:6]


def _running(sessions, today):
    month_start = today.replace(day=1)
    runs = [(session, item) for session in sessions for item in session['items'] if number(item.get('distance_meters'))]
    def summary(selected):
        meters = sum(number(item['distance_meters']) for _, item in selected)
        seconds = sum(number(item.get('duration_seconds')) or 0 for _, item in selected)
        return {'runs': len(selected), 'distance_km': _round(meters / 1000),
                'longest_km': _round(max(number(item['distance_meters']) for _, item in selected) / 1000),
                'pace_s_per_km': round(seconds / (meters / 1000)) if seconds else None} if selected else None
    month = summary([run for run in runs if run[0]['day'] >= month_start])
    recent = summary([run for run in runs if run[0]['day'] > today - timedelta(days=30)])
    if not month and not recent:
        return None
    return {'month': today.strftime('%Y-%m'), 'this_month': month, 'last_30d': recent}


def _training(facts, today, user):
    sessions = _sessions(facts)
    if not sessions:
        return None
    week_start = today - timedelta(days=today.weekday())
    last7 = [s for s in sessions if today - timedelta(days=6) <= s['day'] <= today]
    last28 = [s for s in sessions if s['day'] > today - timedelta(days=28)]
    latest = sessions[-1]
    return {'sessions_week': sum(1 for s in sessions if week_start <= s['day'] <= today), 'week_start': week_start.isoformat(),
            'planned_days': (user.get('training_profile') or {}).get('available_days'),
            'sessions_7d': len(last7), 'minutes_7d': round(sum(s['minutes'] for s in last7)),
            'load_7d': round(sum(s['load'] for s in last7)), 'sessions_28d': len(last28),
            'disciplines_28d': dict(Counter(s['discipline'] for s in last28 if s['discipline'])),
            # Oldest first: sessions and load in each of the last four calendar weeks.
            'weeks': [{'week_start': start.isoformat(),
                       'sessions': sum(1 for s in sessions if start <= s['day'] < start + timedelta(days=7)),
                       'load': round(sum(s['load'] for s in sessions if start <= s['day'] < start + timedelta(days=7)))}
                      for start in (week_start - timedelta(weeks=offset) for offset in range(3, -1, -1))],
            'last': {'name': latest['name'], 'discipline': latest['discipline'],
                     'at': latest['at'].astimezone(LOCAL).strftime('%Y-%m-%d %H:%M')},
            'exercises': _exercises(sessions), 'running': _running(sessions, today)}


def build_user_model(facts, now=None):
    now = now or datetime.now(timezone.utc)
    today = local_day(now)
    groups = defaultdict(list)
    for fact in facts:
        groups[fact.get('kind')].append(fact)
    user = next((fact.get('data') or {} for fact in groups['User']), {})
    metrics = _metrics(groups['BodyMetric'])
    body = _body(metrics)
    return {'version': MODEL_VERSION, 'computed_at': now.isoformat(), 'today': today.isoformat(),
            'profile': _profile(user, metrics), 'body': body, 'goal': _goal(groups['Goal'], metrics, body, today),
            'nutrition': _nutrition(groups['Meal'], today), 'training': _training(groups['Training'], today, user)}


def model_links(model):
    """Graph-native habits: which catalog foods and exercises define this user."""
    foods = [{'key': f['key'], 'count': f['count'], 'last_date': f['last_date']}
             for f in ((model.get('nutrition') or {}).get('top_foods') or []) if f.get('key')]
    exercises = [{'key': e['key'], 'sessions': e['sessions'], 'last_date': e['last_date'],
                  'best_e1rm_kg': e.get('best_e1rm_kg'), 'distance_km': e.get('distance_km')}
                 for e in ((model.get('training') or {}).get('exercises') or []) if e.get('key')]
    return foods, exercises


# ---------------------------------------------------------------------------
# Prompt rendering: one compact Vietnamese line per section, explicit dates.
# ---------------------------------------------------------------------------

def _n(value):
    return f'{round(float(value), 2):g}'


def _signed(value):
    return ('+' if value > 0 else '') + _n(value)


def _pace(seconds):
    return f'{int(seconds) // 60}:{int(seconds) % 60:02d}/km'


def _join(*parts):
    return ' · '.join(str(part) for part in parts if part not in (None, '', []))


def _day(iso, today):
    if today is None:
        return iso
    if iso == today.isoformat():
        return f'hôm nay ({iso})'
    if iso == (today - timedelta(days=1)).isoformat():
        return f'hôm qua ({iso})'
    return iso


def profile_line(model):
    profile = model.get('profile')
    if not profile:
        return None
    training = profile.get('training') or {}
    plan = None
    if training.get('available_days'):
        plan = f"{training['available_days']} buổi/tuần" + (f" × {training['session_minutes']} phút" if training.get('session_minutes') else '')
    return 'Hồ sơ: ' + _join(
        f"{profile['age']} tuổi" if profile.get('age') else None,
        f"cao {_n(profile['height_cm'])} cm" if profile.get('height_cm') else None,
        f"nặng {_n(profile['weight_kg'])} kg" if profile.get('weight_kg') else None,
        f"BMI {_n(profile['bmi'])}" if profile.get('bmi') else None,
        f"trình độ tập {LEVELS.get(training.get('experience_level'), training.get('experience_level'))}" if training.get('experience_level') else None,
        f"trọng tâm {FOCUS.get(training.get('primary_focus'), training.get('primary_focus'))}" if training.get('primary_focus') else None,
        plan, 'dụng cụ: ' + ', '.join(training['equipment']) if training.get('equipment') else None)


def body_line(model):
    body = model.get('body')
    if not body:
        return None
    latest = body['latest']
    changes = [f"{_signed(c['delta_kg'])} kg so với {c['since']} ({c['days']} ngày)" for c in body['changes']]
    rate = f" ~{_n(abs(body['rate_kg_per_week']))} kg/tuần" if body.get('rate_kg_per_week') and body['trend'] != 'ổn định' else ''
    return 'Cân nặng: ' + _join(f"{_n(latest['weight_kg'])} kg ({latest['date']})", *changes, f"xu hướng {body['trend']}{rate}")


def goal_line(model):
    goal = model.get('goal')
    if not goal:
        return None
    target = None
    if goal.get('target_weight_kg') is not None:
        target = f"đích {_n(goal['target_weight_kg'])} kg" + (' (theo tiêu đề)' if goal.get('target_source') == 'title' else '')
    path = None
    if goal.get('start_weight_kg') is not None:
        path = f"từ {_n(goal['start_weight_kg'])} kg ({goal['start_weight_date']}) → hiện {_n(goal['current_weight_kg'])} kg"
    pace = None
    if goal.get('required_kg_per_week') is not None:
        pace = f"cần {_signed(goal['required_kg_per_week'])} kg/tuần"
        if goal.get('actual_kg_per_week') is not None:
            pace += f", thực tế {_signed(goal['actual_kg_per_week'])} kg/tuần → " + ('đúng tiến độ' if goal.get('on_track') else 'chậm hơn kế hoạch')
    deadline = None
    if goal.get('target_date'):
        deadline = f"hạn {goal['target_date']}" + (f" (còn {goal['days_left']} ngày)" if goal.get('days_left') is not None else '')
    return 'Mục tiêu: ' + _join(
        goal.get('title'), target, path,
        'đã đạt' if goal.get('achieved') else (f"còn {_n(goal['remaining_kg'])} kg" if goal.get('remaining_kg') is not None else None),
        f"đạt {goal['progress_pct']}%" if goal.get('progress_pct') is not None else None, deadline, pace)


def nutrition_line(model, today):
    nutrition = model.get('nutrition')
    if not nutrition:
        return None
    average = None
    if nutrition.get('avg_kcal') is not None:
        average = (f"TB {nutrition['avg_kcal']} kcal và {_n(nutrition['avg_protein_g'])} g protein mỗi ngày có ghi "
                   f"({nutrition['logged_days']}/{nutrition['window_days']} ngày, {nutrition['window_start']} → {nutrition['window_end']})")
    days = [f"{_day(d['date'], today)}: {_n(d['kcal'])} kcal, {_n(d['protein_g'])} g protein, {d['meals']} bữa"
            for d in (nutrition.get('today'), nutrition.get('yesterday')) if d]
    partial = (f"TB {_n(nutrition['avg_meals_per_logged_day'])} bữa/ngày nên có thể chưa ghi đủ, trung bình có thể thấp hơn thực tế"
               if nutrition.get('likely_incomplete_logging') else None)
    return 'Dinh dưỡng: ' + _join(average, *days, partial,
                                  'một số món thiếu dữ liệu dinh dưỡng' if nutrition.get('incomplete') else None)


def foods_line(model):
    foods = (model.get('nutrition') or {}).get('top_foods') or []
    if not foods:
        return None
    return 'Món hay ăn (90 ngày): ' + ', '.join(f"{f['name']} ({f['count']} lần, gần nhất {f['last_date']})" for f in foods[:5])


def training_line(model, today):
    training = model.get('training')
    if not training:
        return None
    week = ('tuần này ' if today else 'tuần ') + f"(từ {training['week_start']}) {training['sessions_week']} buổi" + (
        f" / kế hoạch {training['planned_days']}" if training.get('planned_days') else '')
    disciplines = ', '.join(f"{count} {DISCIPLINES.get(name, name)}" for name, count in training['disciplines_28d'].items())
    last = training['last']
    return 'Tập luyện: ' + _join(
        week, f"7 ngày: {training['sessions_7d']} buổi, {training['minutes_7d']} phút, tải {training['load_7d']}",
        f"28 ngày: {training['sessions_28d']} buổi" + (f" ({disciplines})" if disciplines else ''),
        f"gần nhất {last['name']} {_day(last['at'][:10], today)}{last['at'][10:]}")


def exercises_line(model):
    exercises = (model.get('training') or {}).get('exercises') or []
    if not exercises:
        return None
    def describe(entry):
        parts = [f"{entry['sessions']} buổi"]
        if entry.get('best_e1rm_kg'):
            first = entry.get('first_e1rm_kg')
            parts.append(f"e1RM {_n(first)} → {_n(entry['best_e1rm_kg'])} kg" if first and first != entry['best_e1rm_kg'] else f"e1RM {_n(entry['best_e1rm_kg'])} kg")
        if entry.get('distance_km'):
            parts.append(f"tổng {_n(entry['distance_km'])} km")
        return f"{entry['name']} ({', '.join(parts)})"
    return 'Bài tập chính: ' + '; '.join(describe(entry) for entry in exercises[:4])


def running_line(model):
    running = (model.get('training') or {}).get('running')
    if not running:
        return None
    month, recent = running.get('this_month'), running.get('last_30d')
    def describe(summary):
        return _join(f"{_n(summary['distance_km'])} km / {summary['runs']} lần", f"dài nhất {_n(summary['longest_km'])} km",
                     f"pace TB {_pace(summary['pace_s_per_km'])}" if summary.get('pace_s_per_km') else None)
    parts = [f"tháng {running['month']}: {describe(month)}" if month else None]
    if recent and recent != month:
        parts.append(f"30 ngày: {describe(recent)}")
    return 'Chạy bộ: ' + _join(*parts)


def conversation_line(intents):
    if not intents:
        return None
    ranked = ', '.join(f"{intent_label(i['intent'])} ({i['turns']} lượt)" for i in intents[:5])
    latest = max(intents, key=lambda i: str(i.get('last_at') or ''))
    when = parse_time(latest.get('last_at'))
    return 'Hội thoại 30 ngày: hay hỏi ' + ranked + (
        f" · gần nhất {intent_label(latest['intent'])} {when.astimezone(LOCAL).strftime('%Y-%m-%d %H:%M')}" if when else '')


SECTION_RENDERERS = {
    'profile': lambda model, intents, today: profile_line(model),
    'body': lambda model, intents, today: body_line(model),
    'goal': lambda model, intents, today: goal_line(model),
    'nutrition': lambda model, intents, today: nutrition_line(model, today),
    'foods': lambda model, intents, today: foods_line(model),
    'training': lambda model, intents, today: training_line(model, today),
    'exercises': lambda model, intents, today: exercises_line(model),
    'running': lambda model, intents, today: running_line(model),
    'conversation': lambda model, intents, today: conversation_line(intents),
}


def section_lines(model, sections, intents=(), now=None):
    """Rendered lines in relevance order; a stale model keeps explicit dates."""
    model = model or {}
    today = local_day(now or datetime.now(timezone.utc))
    if model.get('today') and model['today'] != today.isoformat():
        # "Hôm nay" would be wrong for a model computed on another day: dates only.
        today = None
    lines = []
    for section in dict.fromkeys(sections):
        renderer = SECTION_RENDERERS.get(section)
        line = renderer(model, list(intents or []), today) if renderer else None
        if line:
            lines.append(line)
    return lines
