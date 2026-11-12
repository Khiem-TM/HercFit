"""Xác thực JWT (core/security.py): loại token, hạn dùng, xoay khoá và header tự khai báo của agent."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from core.security import create_access_token, create_delegated_token, decode_access_token, decode_bearer
from core.settings import settings

PROFILE = "/api/profile"


def sign(user_id, *, secret=None, audience=None, token_type="access", lifetime=timedelta(minutes=5)):
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "iat": int(now.timestamp()), "nbf": int(now.timestamp()),
              "exp": int((now + lifetime).timestamp()), "iss": settings.JWT_ISSUER,
              "aud": audience or settings.JWT_AUDIENCE, "jti": uuid4().hex, "token_type": token_type}
    return jwt.encode(claims, secret or settings.jwt_secret_value, algorithm="HS256")


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def test_access_token_reads_profile(client, make_user):
    _, headers = await make_user()
    assert (await client.get(PROFILE, headers=headers)).status_code == 200


def test_delegated_token_is_not_a_user_session():
    token, _ = create_delegated_token(uuid4(), consent_version=1)
    with pytest.raises(HTTPException) as error:
        decode_access_token(token)
    assert error.value.status_code == 401


def test_access_token_is_not_a_delegation():
    # Token mang loại "access" nhưng audience của agent: không được nhận như token uỷ quyền.
    with pytest.raises(HTTPException) as error:
        decode_bearer(sign(uuid4(), audience=settings.AGENT_TOKEN_AUDIENCE, token_type="access"))
    assert error.value.status_code == 401
    claims, delegated = decode_bearer(create_access_token({"sub": str(uuid4())}))
    assert delegated is False


async def test_wrong_token_type_is_rejected(client, make_user):
    user_id, _ = await make_user()
    response = await client.get(PROFILE, headers=bearer(sign(user_id, token_type="refresh")))
    assert response.status_code == 401


async def test_expired_token_is_rejected(client, make_user):
    user_id, _ = await make_user()
    expired = sign(user_id, lifetime=-timedelta(seconds=settings.JWT_LEEWAY_SECONDS + 60))
    assert (await client.get(PROFILE, headers=bearer(expired))).status_code == 401


async def test_previous_secret_still_verifies(client, make_user, monkeypatch):
    user_id, _ = await make_user()
    old = "retired-secret-key-for-rotation-test-0002"
    token = sign(user_id, secret=old)
    assert (await client.get(PROFILE, headers=bearer(token))).status_code == 401
    monkeypatch.setattr(settings, "JWT_PREVIOUS_SECRET_KEYS", [SecretStr(old)])
    assert (await client.get(PROFILE, headers=bearer(token))).status_code == 200


async def test_self_declared_agent_header_needs_delegation(client, make_user, monkeypatch):
    user_id, headers = await make_user()
    agent = {**headers, "X-HercFit-Client": "agent"}
    monkeypatch.setattr(settings, "AGENT_DELEGATION_REQUIRED", False)
    assert (await client.get(PROFILE, headers=agent)).status_code == 200
    monkeypatch.setattr(settings, "AGENT_DELEGATION_REQUIRED", True)
    assert (await client.get(PROFILE, headers=agent)).status_code == 401
    delegated, _ = create_delegated_token(user_id, consent_version=1)
    assert (await client.get(PROFILE, headers={**bearer(delegated), "X-HercFit-Client": "agent"})).status_code == 200
