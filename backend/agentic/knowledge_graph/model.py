"""Derived personal knowledge: what an attentive coach remembers about a user.

Pure functions over projected facts, so the worker can rebuild a model at any
time and tests can check every number. Dates are local (Asia/Ho_Chi_Minh).
Only backend business facts feed the stored model; conversation statistics are
aggregated at read time behind the SQL session gate.
"""
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean, median, pstdev
from zoneinfo import ZoneInfo

from schemas.health import (
    ACTIVITY_LABELS, ACTIVITY_ORDER, BMI_LABELS, HRV_DROP_PCT, RHR_ELEVATION_BPM, WHO_ACTIVE_MINUTES_PER_WEEK,
    WORN_DAY_MIN_STEPS, activity_level_from_exercise, activity_level_from_steps, classify_bmi, recommended_sleep_hours,
)

from .intents import label as intent_label

LOCAL = ZoneInfo('Asia/Ho_Chi_Minh')
# 2: device data (activity, sleep, recovery, energy), sex and the declared activity level.
# 3: implausible weigh-ins kept out of trends, one trend/rate source, exercise-aware activity level.
MODEL_VERSION = 3
LEVELS = {'BEGINNER': 'mới bắt đầu', 'INTERMEDIATE': 'trung cấp', 'ADVANCED': 'nâng cao'}
FOCUS = {'STRENGTH': 'sức mạnh', 'RUNNING': 'chạy bộ', 'HYBRID': 'kết hợp sức mạnh và chạy'}
DISCIPLINES = {'STRENGTH': 'sức mạnh', 'ENDURANCE': 'sức bền', 'SPORT': 'thể thao', 'MIXED': 'kết hợp'}
PROFILE_FIELDS = ('experience_level', 'primary_focus', 'available_days', 'session_minutes', 'equipment')
SEX = {'MALE': 'nam', 'FEMALE': 'nữ'}
DAILY_KEYS = ('steps', 'distance_m', 'active_minutes', 'active_zone_minutes', 'total_kcal', 'active_kcal',
              'resting_hr_bpm', 'hrv_ms', 'spo2_avg_pct', 'respiratory_rate', 'vo2_max', 'hydration_ml', 'sleep_minutes')
MIN_WORN_DAYS = 7
# Water, food and clothing move the scale by about 2 kg between weigh-ins; body mass itself
# changes by at most ~0.25 kg/day. A larger change is a data problem, not a trend.
WEIGHT_NOISE_KG = 2.0
WEIGHT_RATE_KG_PER_DAY = 0.25
# A trend needs both a weekly rate and a total change above day-to-day noise.
STABLE_KG_PER_WEEK = 0.1
STABLE_TOTAL_KG = 0.3
# Logged exercise below this (per week) neither raises the activity level nor counts as evidence.
MIN_EXERCISE_MINUTES = 60


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


def _avg(values, digits=None):
    values = [v for v in values if v is not None]
    return round(mean(values), digits) if values else None


def _metrics(facts):
    rows = []
    for fact in facts:
        data = fact.get('data') or {}
        at = parse_time(data.get('recorded_at')) or parse_time(fact.get('source_at'))
        weight, height, fat = number(data.get('weight_kg')), number(data.get('height_cm')), number(data.get('body_fat_pct'))
        # Device samples may carry a single measurement (a body-fat reading without weight).
        if at and (weight or height or fat):
            rows.append({'at': at, 'weight_kg': weight, 'height_cm': height, 'body_fat_pct': fat,
                         'device': (data.get('source') or 'MANUAL') != 'MANUAL'})
    return sorted(rows, key=lambda row: row['at'])


def _days(facts):
    """Device day rollups by local date."""
    days = {}
    for fact in facts:
        data = fact.get('data') or {}
        day = parse_date(data.get('local_date'))
        if day:
            days[day] = {key: number(data.get(key)) for key in DAILY_KEYS}
    return days


def _sleeps(facts):
    sessions = []
    for fact in facts:
        data = fact.get('data') or {}
        start, end, day = parse_time(data.get('start_at')), parse_time(data.get('end_at')), parse_date(data.get('local_date'))
        if start and end and day:
            sessions.append({'day': day, 'start': start, 'end': end, 'nap': bool(data.get('is_nap')),
                             **{key: number(data.get(key)) for key in ('minutes_asleep', 'deep_minutes', 'light_minutes',
                                                                        'rem_minutes', 'efficiency_pct')}})
    return sorted(sessions, key=lambda session: session['end'])


def _workouts(facts):
    workouts = []
    for fact in facts:
        data = fact.get('data') or {}
        day = parse_date(data.get('local_date'))
        if day:
            workouts.append({'day': day, 'type': data.get('exercise_type') or 'OTHER', 'name': data.get('display_name'),
                             'minutes': (number(data.get('active_seconds')) or 0) / 60, 'kcal': number(data.get('energy_kcal')),
                             'distance_km': (number(data.get('distance_m')) or 0) / 1000 or None})
    return sorted(workouts, key=lambda workout: workout['day'])


def _worn(days, start, end):
    """Complete worn days in [start, end): today is still being recorded."""
    return {day: d for day, d in days.items() if start <= day < end and (d['steps'] or 0) >= WORN_DAY_MIN_STEPS}


def _exercise_week(sessions, workouts, today):
    """Exercise minutes per week over the last 28 days, from logged sessions and device workouts.

    A run may be both logged and recorded by a watch: each day counts the larger of the two."""
    start = today - timedelta(days=28)
    logged, recorded = defaultdict(float), defaultdict(float)
    for session in sessions:
        if start < session['day'] <= today:
            logged[session['day']] += session['minutes']
    for workout in workouts:
        if start < workout['day'] <= today:
            recorded[workout['day']] += workout['minutes']
    total = sum(max(logged[day], recorded[day]) for day in set(logged) | set(recorded))
    return round(total / 4) if total else None


def _observed_level(days, exercise_week, today):
    """What the data shows: steps on worn days, raised by exercise the step count misses.

    Exercise is a lower bound (not every session is logged), so it can raise the level but
    never lower it; `basis` says which evidence was used."""
    worn = _worn(days, today - timedelta(days=28), today)
    steps = _avg(d['steps'] for d in worn.values()) if len(worn) >= MIN_WORN_DAYS else None
    candidates = []
    if steps is not None:
        candidates.append(('steps', activity_level_from_steps(steps)))
    if exercise_week is not None and exercise_week >= MIN_EXERCISE_MINUTES:
        candidates.append(('exercise', activity_level_from_exercise(exercise_week)))
    if not candidates:
        return None
    level = max((level for _, level in candidates), key=ACTIVITY_ORDER.index)
    return {'level': level, 'basis': [basis for basis, _ in candidates], 'steps_28d': steps, 'exercise_minutes_week': exercise_week}


def _profile(user, metrics, days, today, observed=None):
    height = next((m['height_cm'] for m in reversed(metrics) if m['height_cm']), None)
    weight = next((m['weight_kg'] for m in reversed(metrics) if m['weight_kg']), None)
    fat = next((m['body_fat_pct'] for m in reversed(metrics) if m['body_fat_pct']), None)
    training = {key: value for key, value in (user.get('training_profile') or {}).items()
                if key in PROFILE_FIELDS and value not in (None, '', [])}
    bmi = _round(weight / (height / 100) ** 2) if weight and height else None
    resting = [d['resting_hr_bpm'] for day, d in days.items() if day > today - timedelta(days=7) and d['resting_hr_bpm']]
    vo2 = next((days[day]['vo2_max'] for day in sorted(days, reverse=True) if days[day]['vo2_max']), None)
    observed = observed or {}
    profile = {'age': user.get('age'), 'sex': user.get('sex'), 'height_cm': height, 'weight_kg': weight,
               'bmi': bmi, 'bmi_class': classify_bmi(bmi), 'body_fat_pct': fat,
               'declared_level': user.get('activity_level'), 'observed_level': observed.get('level'),
               'observed_basis': observed.get('basis'), 'exercise_minutes_week': observed.get('exercise_minutes_week'),
               'resting_hr': round(median(resting)) if resting else None, 'vo2_max': _round(vo2),
               'training': training or None}
    return profile if any(value is not None for value in profile.values()) else None


def _conflicts(profile, observed):
    """Declared versus measured: surfaced to the assistant, never silently resolved."""
    if not profile or not observed:
        return []
    declared, level = profile.get('declared_level'), observed['level']
    if declared not in ACTIVITY_ORDER or abs(ACTIVITY_ORDER.index(declared) - ACTIVITY_ORDER.index(level)) < 2:
        return []
    if ACTIVITY_ORDER.index(level) < ACTIVITY_ORDER.index(declared) and 'steps' not in observed['basis']:
        # Logged sessions alone are a lower bound: missing logs do not contradict a declaration.
        return []
    evidence = ', '.join(filter(None, [f"TB {int(observed['steps_28d'])} bước/ngày" if observed.get('steps_28d') else None,
                                       f"{observed['exercise_minutes_week']} phút tập/tuần" if 'exercise' in observed['basis'] else None]))
    return [f"Mức vận động khai báo '{ACTIVITY_LABELS[declared]}' nhưng dữ liệu ghi nhận "
            f"'{ACTIVITY_LABELS[level]}'" + (f" ({evidence}, 28 ngày)" if evidence else '')]


def _activity(days, workouts, today, observed=None):
    worn28, worn7 = _worn(days, today - timedelta(days=28), today), _worn(days, today - timedelta(days=7), today)
    week = [d for day, d in days.items() if today - timedelta(days=6) <= day <= today]
    recent = [w for w in workouts if w['day'] > today - timedelta(days=7)]
    if not worn28 and not recent and today not in days:
        return None
    minutes = [d['active_minutes'] for d in week if d['active_minutes'] is not None]
    zone = [d['active_zone_minutes'] for d in week if d['active_zone_minutes'] is not None]
    steps28 = _avg((d['steps'] for d in worn28.values()))
    return {'steps_7d': _avg((d['steps'] for d in worn7.values())), 'steps_28d': steps28, 'worn_days_28d': len(worn28),
            'today_steps': (days.get(today) or {}).get('steps'),
            'active_minutes_7d': round(sum(minutes)) if minutes else None,
            'meets_who': sum(minutes) >= WHO_ACTIVE_MINUTES_PER_WEEK if minutes else None,
            'active_zone_minutes_7d': round(sum(zone)) if zone else None,
            'total_kcal_7d': _avg((d['total_kcal'] for d in worn7.values())),
            'observed_level': (observed or {}).get('level'),
            'workouts_7d': len(recent), 'workout_minutes_7d': round(sum(w['minutes'] for w in recent)),
            'workout_types_28d': dict(Counter(w['type'] for w in workouts if w['day'] > today - timedelta(days=28)))}


def _clock(moment):
    return moment.astimezone(LOCAL).strftime('%H:%M')


def _sleep(sessions, today, age):
    main = [s for s in sessions if not s['nap'] and s['minutes_asleep'] and s['day'] > today - timedelta(days=28)]
    if not main:
        return None
    recent = [s for s in main if s['day'] > today - timedelta(days=7)]
    low, high = recommended_sleep_hours(age)
    staged = [s for s in recent if s['deep_minutes'] is not None and s['rem_minutes'] is not None]
    staged_total = sum((s['deep_minutes'] or 0) + (s['light_minutes'] or 0) + (s['rem_minutes'] or 0) for s in staged)
    # Minutes after noon, so 23:30 and 00:30 are an hour apart rather than 23 hours.
    bedtimes = [(s['start'].astimezone(LOCAL).hour * 60 + s['start'].astimezone(LOCAL).minute + 720) % 1440 for s in recent]
    last = main[-1]
    return {'nights_7d': len(recent), 'avg_minutes_7d': _avg(s['minutes_asleep'] for s in recent),
            'avg_minutes_28d': _avg(s['minutes_asleep'] for s in main), 'recommended_hours': [low, high],
            'short_nights_7d': sum(1 for s in recent if s['minutes_asleep'] < low * 60),
            'deep_pct': round(100 * sum(s['deep_minutes'] for s in staged) / staged_total) if staged_total else None,
            'rem_pct': round(100 * sum(s['rem_minutes'] for s in staged) / staged_total) if staged_total else None,
            'bedtime_stdev_min': round(pstdev(bedtimes)) if len(bedtimes) >= 3 else None,
            'last': {'date': last['day'].isoformat(), 'minutes': round(last['minutes_asleep']),
                     'bedtime': _clock(last['start']), 'wake': _clock(last['end'])}}


def _recovery(days, today):
    recent = [d for day, d in days.items() if today - timedelta(days=7) < day <= today]
    base = [d for day, d in days.items() if today - timedelta(days=28) < day <= today - timedelta(days=7)]
    def pair(key, digits=None):
        now, before = [d[key] for d in recent if d[key]], [d[key] for d in base if d[key]]
        return (_avg(now, digits) if len(now) >= 3 else None), (_avg(before, digits) if len(before) >= 7 else None)
    rhr, rhr_base = pair('resting_hr_bpm')
    hrv, hrv_base = pair('hrv_ms', 1)
    spo2 = _avg((d['spo2_avg_pct'] for d in recent), 1)
    if rhr is None and hrv is None and spo2 is None:
        return None
    signals = []
    if rhr is not None and rhr_base is not None and rhr - rhr_base >= RHR_ELEVATION_BPM:
        signals.append('nhịp tim nghỉ cao hơn nền')
    if hrv is not None and hrv_base and 100 * (hrv_base - hrv) / hrv_base >= HRV_DROP_PCT:
        signals.append('HRV thấp hơn nền')
    return {'resting_hr_7d': rhr, 'resting_hr_base': rhr_base, 'hrv_7d': hrv, 'hrv_base': hrv_base,
            'spo2_7d': spo2, 'respiratory_rate_7d': _avg((d['respiratory_rate'] for d in recent), 1), 'signals': signals}


def _energy(meal_facts, days, weights, today):
    """Logged intake against device expenditure on complete days of the last 28.

    `weights` is the consistent weigh-in run (_weight_series), so a bad reading cannot fake a change."""
    totals = defaultdict(lambda: {'kcal': 0.0, 'meals': 0, 'unknown': 0})
    for fact in meal_facts:
        data = fact.get('data') or {}
        at = parse_time(data.get('consumed_at'))
        if at:
            day = totals[local_day(at)]
            kcal = number(data.get('energy_kcal'))
            day['kcal'] += kcal or 0.0
            day['meals'] += 1
            day['unknown'] += kcal is None or bool(data.get('nutrition_incomplete'))
    start = today - timedelta(days=28)
    paired = sorted((day, totals[day]['kcal'], days[day]['total_kcal']) for day in days
                    if start <= day < today and days[day]['total_kcal'] and day in totals
                    and totals[day]['meals'] >= 2 and not totals[day]['unknown'])
    if len(paired) < 3:
        return None
    intake, out = round(mean(p[1] for p in paired)), round(mean(p[2] for p in paired))
    weights = [m for m in weights if local_day(m['at']) >= paired[0][0]]
    return {'days': len(paired), 'start': paired[0][0].isoformat(), 'end': paired[-1][0].isoformat(),
            'intake_kcal': intake, 'expenditure_kcal': out, 'balance_kcal': intake - out,
            'weight_change_kg': _round(weights[-1]['weight_kg'] - weights[0]['weight_kg'], 2) if len(weights) >= 2 else None}


def _plausible(a, b):
    days = abs((b['at'] - a['at']).total_seconds()) / 86400
    return abs(b['weight_kg'] - a['weight_kg']) <= WEIGHT_NOISE_KG + WEIGHT_RATE_KG_PER_DAY * days


def _weight_series(metrics):
    """Weigh-ins a trend may use.

    An isolated reading that disagrees with both neighbours (while they agree) is dropped as a
    spike. An implausible jump that stays (a mistyped entry, a second scale or a device) cannot
    be resolved from the data, so only the latest run of mutually plausible weigh-ins feeds
    changes, rates, goal progress and energy balance, and the jump is reported instead."""
    weights = [m for m in metrics if m['weight_kg'] is not None]
    kept, spikes = [], 0
    for index, row in enumerate(weights):
        following = weights[index + 1] if index + 1 < len(weights) else None
        if kept and following and not _plausible(kept[-1], row) and not _plausible(row, following) \
                and _plausible(kept[-1], following):
            spikes += 1
            continue
        kept.append(row)
    start = len(kept) - 1
    while start > 0 and _plausible(kept[start - 1], kept[start]):
        start -= 1
    jump = None
    if start > 0:
        before, after = kept[start - 1], kept[start]
        jump = {'from_kg': before['weight_kg'], 'from_date': local_day(before['at']).isoformat(),
                'to_kg': after['weight_kg'], 'to_date': local_day(after['at']).isoformat(),
                'sources_differ': before['device'] != after['device']}
    return {'all': weights, 'segment': kept[start:] if kept else [], 'jump': jump, 'spikes': spikes}


def _trend(rate, span_days):
    if rate is None:
        return 'chưa rõ'
    if abs(rate) < STABLE_KG_PER_WEEK or abs(rate) * span_days / 7 < STABLE_TOTAL_KG:
        return 'ổn định'
    return 'giảm' if rate < 0 else 'tăng'


def _body(series, metrics):
    weights, segment = series['all'], series['segment']
    if not weights:
        return None
    latest = weights[-1]  # never a dropped spike: a spike needs a later reading
    changes = []
    for window in (7, 30):
        # The most recent measurement at least ~80% of the window before the latest one.
        base = next((m for m in reversed(segment[:-1]) if (latest['at'] - m['at']).days >= window * .8), None)
        if base and not any(change['since'] == local_day(base['at']).isoformat() for change in changes):
            changes.append({'window': window, 'delta_kg': _round(latest['weight_kg'] - base['weight_kg']),
                            'since': local_day(base['at']).isoformat(),
                            'days': round((latest['at'] - base['at']).total_seconds() / 86400)})
    longest = max(changes, key=lambda change: change['days'], default=None)
    rate = round(longest['delta_kg'] / longest['days'] * 7, 2) if longest and longest['days'] else None
    span = longest['days'] if longest else 0
    # Least-squares slope over the last 30 days: robust to day-to-day water noise and,
    # unlike a moving average, without lag when weigh-ins are sparse. Trend and rate come
    # from this one estimate, so the card never states a direction its rate contradicts.
    recent = [m for m in segment if (latest['at'] - m['at']).days <= 30]
    width = (recent[-1]['at'] - recent[0]['at']).total_seconds() / 86400 if len(recent) >= 2 else 0
    if len(recent) >= 3 and width >= 7:
        xs = [(m['at'] - recent[0]['at']).total_seconds() / 86400 for m in recent]
        ys = [m['weight_kg'] for m in recent]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        denominator = sum((x - mx) ** 2 for x in xs)
        if denominator:
            rate, span = round(sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denominator * 7, 2), width
    fats = [m for m in metrics if m['body_fat_pct'] is not None]
    fat = None
    if fats:
        base = next((m for m in fats if (fats[-1]['at'] - m['at']).days <= 30), fats[0])
        fat = {'pct': fats[-1]['body_fat_pct'], 'date': local_day(fats[-1]['at']).isoformat(),
               'change_30d': _round(fats[-1]['body_fat_pct'] - base['body_fat_pct']) if base is not fats[-1] else None}
    return {'latest': {'weight_kg': latest['weight_kg'], 'date': local_day(latest['at']).isoformat()},
            'body_fat': fat, 'changes': changes, 'rate_kg_per_week': rate, 'trend': _trend(rate, span),
            # The latest implausible jump and dropped spikes: the card asks to re-weigh instead of trending.
            'inconsistent': series['jump'], 'outliers': series['spikes'],
            'series': [{'date': local_day(m['at']).isoformat(), 'weight_kg': m['weight_kg']} for m in weights[-12:]]}


def _target_from_text(*texts):
    for text in texts:
        found = re.findall(r'(\d+(?:[.,]\d+)?)\s*kg', str(text or '').lower())
        if found:
            return float(found[-1].replace(',', '.'))
    return None


def _goal(facts, series, body, today):
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
    # Progress is measured inside the consistent weigh-in run: a jump the data cannot explain
    # is neither progress nor a setback, and a single reading after one is no baseline.
    weights = series['segment']
    if target is None or not weights:
        return result
    if series['jump'] and len(weights) < 2:
        result.update(current_weight_kg=weights[-1]['weight_kg'], weights_inconsistent=True)
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
    series = _weight_series(metrics)
    body = _body(series, metrics)
    days = _days(groups['DailyHealth'])
    workouts = _workouts(groups['DeviceWorkout'])
    observed = _observed_level(days, _exercise_week(_sessions(groups['Training']), workouts, today), today)
    profile = _profile(user, metrics, days, today, observed)
    return {'version': MODEL_VERSION, 'computed_at': now.isoformat(), 'today': today.isoformat(),
            'profile': profile, 'body': body, 'goal': _goal(groups['Goal'], series, body, today),
            'nutrition': _nutrition(groups['Meal'], today), 'training': _training(groups['Training'], today, user),
            'activity': _activity(days, workouts, today, observed),
            'sleep': _sleep(_sleeps(groups['SleepSession']), today, user.get('age')),
            'recovery': _recovery(days, today), 'energy': _energy(groups['Meal'], days, series['segment'], today),
            'conflicts': _conflicts(profile, observed)}


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
    bmi = None
    if profile.get('bmi'):
        bmi = f"BMI {_n(profile['bmi'])}" + (f" ({BMI_LABELS[profile['bmi_class']]}, ngưỡng châu Á)" if profile.get('bmi_class') else '')
    level = None
    if profile.get('declared_level') or profile.get('observed_level'):
        basis = ' và '.join(filter(None, [
            'bước chân' if 'steps' in (profile.get('observed_basis') or []) else None,
            f"~{profile['exercise_minutes_week']} phút tập/tuần" if 'exercise' in (profile.get('observed_basis') or []) else None]))
        level = 'vận động ' + _join(
            f"khai báo {ACTIVITY_LABELS.get(profile['declared_level'], profile['declared_level'])}" if profile.get('declared_level') else None,
            f"thực tế {ACTIVITY_LABELS[profile['observed_level']]}" + (f" (theo {basis})" if basis else '')
            if profile.get('observed_level') else None).replace(' · ', ', ')
    return 'Hồ sơ: ' + _join(
        f"{profile['age']} tuổi" if profile.get('age') else None, SEX.get(profile.get('sex')),
        f"cao {_n(profile['height_cm'])} cm" if profile.get('height_cm') else None,
        f"nặng {_n(profile['weight_kg'])} kg" if profile.get('weight_kg') else None, bmi,
        f"mỡ {_n(profile['body_fat_pct'])}%" if profile.get('body_fat_pct') else None, level,
        f"nhịp tim nghỉ {profile['resting_hr']} bpm" if profile.get('resting_hr') else None,
        f"VO2max {_n(profile['vo2_max'])}" if profile.get('vo2_max') else None,
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
    fat = body.get('body_fat')
    fat_text = None
    if fat:
        fat_text = f"mỡ {_n(fat['pct'])}% ({fat['date']}" + (f", {_signed(fat['change_30d'])} điểm/30 ngày)" if fat.get('change_30d') else ')')
    jump, note = body.get('inconsistent'), None
    if jump:
        note = (f"số đo lệch bất thường {_n(jump['from_kg'])} kg ({jump['from_date']}) → {_n(jump['to_kg'])} kg ({jump['to_date']})"
                + (', khác nguồn nhập tay/thiết bị' if jump.get('sources_differ') else '')
                + ': chưa tính xu hướng qua mốc này, nên cân lại cùng điều kiện')
    outliers = f"bỏ qua {body['outliers']} lần cân lệch" if body.get('outliers') else None
    return 'Cân nặng: ' + _join(f"{_n(latest['weight_kg'])} kg ({latest['date']})", *changes, f"xu hướng {body['trend']}{rate}",
                                fat_text, note, outliers)


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
        f"đạt {goal['progress_pct']}%" if goal.get('progress_pct') is not None else None, deadline, pace,
        'chưa tính tiến độ vì số đo cân lệch bất thường' if goal.get('weights_inconsistent') else None)


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


def _duration(minutes):
    minutes = round(minutes)
    return f"{minutes // 60}g{minutes % 60:02d}"


def activity_line(model, today):
    activity = model.get('activity')
    if not activity:
        return None
    steps = None
    if activity.get('steps_7d') is not None:
        steps = f"TB {activity['steps_7d']} bước/ngày (7 ngày)" + (
            f", {activity['steps_28d']} (28 ngày, {activity['worn_days_28d']} ngày đeo)" if activity.get('steps_28d') else '')
    minutes = None
    if activity.get('active_minutes_7d') is not None:
        minutes = f"{activity['active_minutes_7d']} phút vận động/7 ngày " + (
            '(đạt' if activity.get('meets_who') else '(chưa đạt') + f" WHO {WHO_ACTIVE_MINUTES_PER_WEEK})"
    return 'Vận động (thiết bị): ' + _join(
        steps, f"{'hôm nay' if today else model.get('today')} {activity['today_steps']:g} bước" if activity.get('today_steps') is not None else None,
        minutes, f"tiêu hao TB {activity['total_kcal_7d']} kcal/ngày (ước tính)" if activity.get('total_kcal_7d') else None,
        f"{activity['workouts_7d']} buổi ghi bởi thiết bị, {activity['workout_minutes_7d']} phút" if activity.get('workouts_7d') else None)


def sleep_line(model):
    sleep = model.get('sleep')
    if not sleep:
        return None
    low, high = sleep['recommended_hours']
    average = None
    if sleep.get('avg_minutes_7d') is not None:
        average = f"TB {_duration(sleep['avg_minutes_7d'])}/đêm ({sleep['nights_7d']} đêm, khuyến nghị {low:g}–{high:g} giờ" + (
            f", {sleep['short_nights_7d']} đêm thiếu)" if sleep.get('short_nights_7d') else ')')
    stages = f"sâu {sleep['deep_pct']}%, REM {sleep['rem_pct']}%" if sleep.get('deep_pct') is not None else None
    last = sleep['last']
    return 'Giấc ngủ (thiết bị): ' + _join(
        average, stages, f"giờ đi ngủ lệch ±{sleep['bedtime_stdev_min']} phút" if sleep.get('bedtime_stdev_min') else None,
        f"gần nhất {last['date']} {_duration(last['minutes'])} ({last['bedtime']}→{last['wake']})")


def recovery_line(model):
    recovery = model.get('recovery')
    if not recovery:
        return None
    def compare(value, base, unit):
        return f"{_n(value)} {unit}" + (f" (nền 28 ngày {_n(base)})" if base is not None else '')
    return 'Phục hồi (thiết bị): ' + _join(
        'nhịp tim nghỉ 7 ngày ' + compare(recovery['resting_hr_7d'], recovery['resting_hr_base'], 'bpm') if recovery.get('resting_hr_7d') else None,
        'HRV ' + compare(recovery['hrv_7d'], recovery['hrv_base'], 'ms') if recovery.get('hrv_7d') else None,
        f"SpO2 {_n(recovery['spo2_7d'])}%" if recovery.get('spo2_7d') else None,
        'tín hiệu cần nghỉ thêm: ' + ', '.join(recovery['signals']) + ' (không phải chẩn đoán)' if recovery.get('signals') else None)


def energy_line(model):
    energy = model.get('energy')
    if not energy:
        return None
    balance = energy['balance_kcal']
    direction = 'thâm hụt' if balance < 0 else 'dư'
    return 'Cân bằng năng lượng: ' + _join(
        f"{energy['days']} ngày đủ dữ liệu ({energy['start']} → {energy['end']}): nạp TB {energy['intake_kcal']} kcal, "
        f"thiết bị ghi tiêu hao {energy['expenditure_kcal']} kcal → {direction} ~{abs(balance)} kcal/ngày",
        f"cân {_signed(energy['weight_change_kg'])} kg" if energy.get('weight_change_kg') is not None else None,
        'calo thiết bị là ước tính')


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
    'activity': lambda model, intents, today: activity_line(model, today),
    'sleep': lambda model, intents, today: sleep_line(model),
    'recovery': lambda model, intents, today: recovery_line(model),
    'energy': lambda model, intents, today: energy_line(model),
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
