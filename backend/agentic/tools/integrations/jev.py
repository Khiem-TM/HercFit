"""Small, non-generative System One client. Never log requests or HTTP bodies."""
import json
import asyncio
import math
import re
import time
from typing import Any

import httpx


class JevError(Exception):
    """An intentionally safe reason code, never a gateway response or URL."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def number(value, minimum=0, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise JevError('invalid_response')
    if value < minimum or (maximum is not None and value > maximum):
        raise JevError('invalid_response')
    return value


def build_payload(projection: Any, questions: dict, model: str) -> dict:
    if not isinstance(model, str) or not model.strip():
        raise JevError('missing_model')
    if not isinstance(questions, dict) or not 1 <= len(questions) <= 128:
        raise JevError('invalid_questions')
    for name, question in questions.items():
        if not isinstance(name, str) or not name or not isinstance(question, dict):
            raise JevError('invalid_questions')
        kind, criteria = question.get('type'), question.get('criteria')
        instructions = question.get('instructions')
        if instructions is not None and not isinstance(instructions, str):
            raise JevError('invalid_questions')
        if kind == 'noul':
            if not instructions and not criteria:
                raise JevError('invalid_questions')
        elif kind == 'choice':
            if (not isinstance(criteria, dict) or not 1 <= len(criteria) <= 255
                    or any(not isinstance(k, str) or not k or not isinstance(v, str) for k, v in criteria.items())):
                raise JevError('invalid_questions')
        elif kind == 'score':
            if not isinstance(criteria, list) or not 1 <= len(criteria) <= 10 or any(not isinstance(v, str) for v in criteria):
                raise JevError('invalid_questions')
        else:
            raise JevError('invalid_questions')
    return {'model': model, 'state': projection, 'questions': questions}


def encode_payload(payload: dict) -> bytes:
    try:
        return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    except (ValueError, TypeError, OverflowError) as exc:
        raise JevError('invalid_payload') from exc


def validate_response(data, questions):
    if not isinstance(data, dict) or not isinstance(data.get('answers'), dict):
        raise JevError('invalid_response')
    if set(data['answers']) != set(questions):
        raise JevError('invalid_response')
    model = data.get('model')
    if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,255}', model):
        raise JevError('invalid_response')
    answers = {}
    for name, question in questions.items():
        raw, kind = data['answers'][name], question['type']
        if not isinstance(raw, dict) or raw.get('type') != kind:
            raise JevError('invalid_response')
        answer = {'type': kind}
        if kind == 'noul':
            answer['noul'] = number(raw.get('noul'), 0, 1)
        else:
            answer['confidence'] = number(raw.get('confidence'), 0, 1)
            labels = list(question['criteria']) if kind == 'choice' else [str(i) for i in range(len(question['criteria']))]
            if kind == 'choice':
                if raw.get('choice') not in labels:
                    raise JevError('invalid_response')
                answer['choice'] = raw['choice']
            else:
                answer['score'] = number(raw.get('score'), 0, len(labels) - 1)
            probabilities = raw.get('probabilities')
            if not isinstance(probabilities, dict) or set(probabilities) != set(labels):
                raise JevError('invalid_response')
            answer['probabilities'] = {label: number(probabilities[label], 0, 1) for label in labels}
            if abs(sum(answer['probabilities'].values()) - 1) > .02:
                raise JevError('invalid_response')
            if kind == 'choice':
                if answer['probabilities'][answer['choice']] < max(answer['probabilities'].values()):
                    raise JevError('invalid_response')
            else:
                expected = sum(int(label) * probability for label, probability in answer['probabilities'].items())
                if abs(answer['score'] - expected) > .02:
                    raise JevError('invalid_response')
                if 'legend' in raw and raw['legend'] != dict(zip(labels, question['criteria'])):
                    raise JevError('invalid_response')
        answers[name] = answer
    usage = None
    raw_usage = data.get('usage')
    if isinstance(raw_usage, dict):
        # LiteLLM deployments expose either System One or OpenAI token names.
        inp = raw_usage.get('input_tokens', raw_usage.get('prompt_tokens'))
        out = raw_usage.get('output_tokens', raw_usage.get('completion_tokens'))
        if all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for v in (inp, out)):
            usage = {'input_tokens': inp, 'output_tokens': out, 'total_tokens': inp + out}
    cost = data.get('response_cost')
    if cost is not None:
        try:
            cost = float(number(cost))
        except JevError:
            cost = None
    return {'answers': answers, 'model': model, 'usage': usage, 'cost': cost}


class JevClient:
    def __init__(self, base_url='https://litellm.otanicloud.link/v1', key='', *, timeout=3, transport=None):
        if not isinstance(base_url, str):
            settings = base_url
            base_url = settings.JEV_BASE_URL
            secret = getattr(settings, 'JEV_API_KEY', None)
            key = secret.get_secret_value() if secret else ''
            timeout = settings.JEV_TIMEOUT_SECONDS
        self.http = httpx.AsyncClient(base_url=base_url.rstrip('/') + '/',
                                     headers={'Authorization': 'Bearer ' + key} if key else {},
                                     timeout=timeout, transport=transport, follow_redirects=False)
        self.timeout = timeout

    async def close(self):
        await self.http.aclose()

    async def models(self):
        try:
            async with asyncio.timeout(self.timeout):
                response = await self.http.get('models')
            if response.is_error:
                raise JevError('http_' + str(response.status_code))
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get('data'), list):
                raise JevError('invalid_response')
            models = [item['id'] for item in data['data'] if isinstance(item, dict) and isinstance(item.get('id'), str)]
            return sorted(set(models))
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise JevError('timeout') from exc
        except httpx.TransportError as exc:
            raise JevError('transport_error') from exc
        except (ValueError, TypeError) as exc:
            raise JevError('invalid_response') from exc

    async def evaluate(self, projection, questions, model):
        body = encode_payload(build_payload(projection, questions, model))
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.timeout):
                response = await self.http.post('systemone', content=body, headers={'Content-Type': 'application/json'})
            if response.is_error:
                raise JevError('http_' + str(response.status_code))
            result = validate_response(response.json(), questions)
            # LiteLLM commonly accounts cost in a response header rather than JSON.
            if result['cost'] is None:
                try:
                    value = float(response.headers['x-litellm-response-cost'])
                    result['cost'] = float(number(value))
                except (KeyError, ValueError, JevError):
                    pass
            result['duration_ms'] = round((time.monotonic() - started) * 1000, 3)
            return result
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise JevError('timeout') from exc
        except httpx.TransportError as exc:
            raise JevError('transport_error') from exc
        except (ValueError, TypeError) as exc:
            raise JevError('invalid_response') from exc
