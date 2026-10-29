"""Bounded, durable Jev decisions; never retain the material being evaluated."""
import asyncio
import copy
import hashlib
import re
import time
from uuid import uuid4

from psycopg.types.json import Jsonb
from observability import observed

from agentic.tools.integrations.jev import JevError, build_payload, encode_payload
from agentic.core.context import request_context


_SECRET_KEYS = frozenset(('token', 'access_token', 'refresh_token', 'authorization', 'api_key',
                          'password', 'user_id', 'session_id', 'run_id', 'email', 'phone',
                          'full_name', 'first_name', 'last_name'))
_EMAIL = re.compile(r'\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b', re.I)
_PHONE = re.compile(r'(?<!\w)(?:\+?\d[\s().-]?){10,15}(?!\w)')
_BEARER = re.compile(r'\bBearer\s+[^\s,;"\']+', re.I)


def _sanitize(value, private):
    if isinstance(value, dict):
        return {str(k): _sanitize(v, private) for k, v in value.items() if str(k).lower() not in _SECRET_KEYS}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v, private) for v in value]
    if isinstance(value, str):
        for secret in private:
            value = value.replace(secret, '[redacted]')
        return _BEARER.sub('[redacted]', _PHONE.sub('[redacted]', _EMAIL.sub('[redacted]', value)))
    return value


class PostgresJevLedger:
    def __init__(self, store):
        self.store = store

    async def reserve(self, state, phase, fingerprint, mode):
        run_id, session_id, user_id = state['run_id'], state['session_id'], state['user_id']
        async with self.store.pool.connection() as conn:
            async with conn.transaction():
                # Serialize both cache checks and counters before network I/O.
                await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('jev:' + run_id,))
                await conn.execute('''INSERT INTO agent_jev_runs(run_id,session_id,user_id,mode)
                    SELECT %s,%s,%s,%s FROM agent_sessions WHERE session_id=%s AND user_id=%s
                    ON CONFLICT(run_id) DO NOTHING''', (run_id, session_id, user_id, mode, session_id, user_id))
                run = await (await conn.execute('SELECT * FROM agent_jev_runs WHERE run_id=%s FOR UPDATE', (run_id,))).fetchone()
                if not run or run['session_id'] != session_id or str(run['user_id']) != user_id:
                    return {'status': 'owner_mismatch', 'mode': mode}
                mode = run['mode']
                row = await (await conn.execute('''SELECT * FROM agent_jev_evaluations
                    WHERE run_id=%s AND phase=%s AND fingerprint=%s''', (run_id, phase, fingerprint))).fetchone()
                if row:
                    return {'status': 'cached' if row['status'] == 'complete' else 'pending',
                            'mode': mode, 'result': row['result'], 'evaluation_id': str(row['evaluation_id'])}
                kind, limit = ('routing', 1) if phase == 'routing' else ('research', 2)
                if run[kind] >= limit:
                    return {'status': 'budget_exhausted', 'mode': mode}
                await conn.execute(f'UPDATE agent_jev_runs SET {kind}={kind}+1 WHERE run_id=%s', (run_id,))
                evaluation_id = str(uuid4())
                await conn.execute('''INSERT INTO agent_jev_evaluations(run_id,phase,fingerprint,evaluation_id)
                    VALUES (%s,%s,%s,%s)''', (run_id, phase, fingerprint, evaluation_id))
                return {'status': 'reserved', 'mode': mode, 'evaluation_id': evaluation_id}

    async def complete(self, evaluation_id, result):
        async with self.store.pool.connection() as conn:
            await conn.execute('''UPDATE agent_jev_evaluations SET status='complete',result=%s,completed_at=now()
                WHERE evaluation_id=%s AND status='pending' ''', (Jsonb(result), evaluation_id))


class JevService:
    def __init__(self, client, store, settings, *, ledger=None):
        self.client, self.settings = client, settings
        self.ledger = ledger if ledger is not None else PostgresJevLedger(store)

    def selected_mode(self, state):
        mode = self.settings.JEV_MODE
        if mode != 'enforce':
            return mode
        # Pin by business run; changing percentage never selects by request/retry.
        bucket = int(hashlib.sha256(str(state.get('run_id', '')).encode()).hexdigest(), 16) % 100
        return 'enforce' if bucket < getattr(self.settings, 'JEV_ENFORCE_PERCENT', 100) else 'shadow'

    @observed('jev.evaluate', 'tool', capture=('phase',), output=False)
    async def evaluate(self, state, phase, projection, questions):
        result = await self._evaluate(state, phase, projection, questions)
        # One source for node-level measured usage; diagnostic graph state is not billing.
        from agentic.observability.telemetry import record_jev_result
        record_jev_result(result)
        return result

    async def _evaluate(self, state, phase, projection, questions):
        started = time.monotonic()
        mode = self.selected_mode(state)
        result = {'status': 'unknown', 'answers': {}, 'mode': mode, 'enforced': mode == 'enforce',
                  'phase': phase, 'reason': None, 'usage': None, 'model': None, 'cost': None,
                  'duration_ms': 0, 'cached': False, 'attempted': False,
                  'policy_version': getattr(self.settings, 'JEV_POLICY_VERSION', 'v1')}
        def unknown(reason):
            result.update(reason=reason, duration_ms=round((time.monotonic() - started) * 1000, 3))
            return result
        if mode == 'off':
            return unknown('disabled')
        if phase not in {'routing', 'local', 'final'}:
            return unknown('invalid_phase')
        if not all(isinstance(state.get(k), str) and state[k] for k in ('run_id', 'user_id', 'session_id')):
            return unknown('missing_run_identity')
        secret = getattr(self.settings, 'JEV_API_KEY', None)
        if not secret or not self.settings.JEV_MODEL:
            return unknown('not_configured')
        if not isinstance(questions, dict) or not 1 <= len(questions) <= (6 if phase == 'routing' else 3):
            return unknown('question_limit')
        private = [state[k] for k in ('run_id', 'user_id', 'session_id')]
        context = request_context.get(None)
        if context:
            if context.user_id != state['user_id']:
                return unknown('owner_mismatch')
            private.extend([context.token, context.user_id, *context.private_values])
        private.append(secret.get_secret_value() if hasattr(secret, 'get_secret_value') else str(secret))
        private = sorted({v for v in private if isinstance(v, str) and len(v) >= 3}, key=len, reverse=True)
        try:
            projection = _sanitize(projection, private)
            questions = _sanitize(questions, private)
            payload = build_payload(projection, questions, self.settings.JEV_MODEL)
            body = encode_payload(payload)
            if len(body) > (8192 if phase == 'routing' else 32768):
                return unknown('payload_limit')
            fingerprint = hashlib.sha256(encode_payload({'payload': payload, 'policy': result['policy_version'],
                                          'gateway': self.settings.JEV_BASE_URL})).hexdigest()
        except JevError as exc:
            return unknown(exc.reason)
        result['fingerprint'] = fingerprint
        try:
            reservation = await self.ledger.reserve(state, phase, fingerprint, mode)
        except Exception:
            return unknown('ledger_unavailable')
        mode = reservation['mode']
        result.update(mode=mode, enforced=mode == 'enforce')
        if reservation['status'] == 'cached':
            saved = copy.deepcopy(reservation['result'])
            saved.update(cached=True, attempted=False, duration_ms=round((time.monotonic() - started) * 1000, 3),
                         evaluation_id=reservation['evaluation_id'])
            return saved
        if reservation.get('evaluation_id'):
            result['evaluation_id'] = reservation['evaluation_id']
        if reservation['status'] != 'reserved':
            return unknown(reservation['status'])
        result['attempted'] = True
        try:
            async with asyncio.timeout(getattr(self.settings, 'JEV_TIMEOUT_SECONDS', 3)):
                decision = await self.client.evaluate(projection, questions, self.settings.JEV_MODEL)
            result.update(decision, status='ok', reason=None)
            if result['cost'] is None and result['usage'] is not None:
                inp = getattr(self.settings, 'JEV_INPUT_PRICE_PER_MILLION', None)
                out = getattr(self.settings, 'JEV_OUTPUT_PRICE_PER_MILLION', None)
                if inp is not None and out is not None:
                    result['cost'] = (result['usage']['input_tokens'] * inp + result['usage']['output_tokens'] * out) / 1_000_000
        except JevError as exc:
            unknown(exc.reason)
        except TimeoutError:
            unknown('timeout')
        except asyncio.CancelledError:
            # The provider may have billed this attempt even though no response
            # reached us. Keep its reservation pending, and record unknown usage.
            from agentic.observability.telemetry import record_jev_result
            record_jev_result(unknown('cancelled'))
            raise
        except Exception:
            unknown('client_error')
        # Cancelled requests leave a durable pending reservation to prevent reissue.
        result['duration_ms'] = round((time.monotonic() - started) * 1000, 3)
        try:
            await self.ledger.complete(result['evaluation_id'], result)
        except Exception:
            # Preserve a known rejection in this response/checkpoint, even if the
            # cache write failed. The durable pending row still prevents reissue.
            result['reason'] = 'ledger_write_failed'
        return result
