"""Exercise the isolated production Compose stack using synthetic accounts only."""

import json
import os
import re
import subprocess
import sys
import time
from http.cookies import SimpleCookie
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


def main() -> int:
    project = os.environ['CI_STACK_PROJECT']
    if not project.startswith('fincore-ci-'):
        raise ValueError('Use a dedicated fincore-ci-* Compose project')
    origin = os.environ['PUBLIC_APP_ORIGIN']
    if not urlsplit(origin).hostname.endswith('.example'):
        raise ValueError('Use a synthetic .example HTTPS origin')
    base = 'http://127.0.0.1:' + os.environ.get('FRONTEND_PORT', '13000')
    mailpit = 'http://127.0.0.1:' + os.environ.get('MAILPIT_UI_PORT', '18027')
    trusted = {
        'X-FinCore-Proxy-Token': os.environ['FRONTEND_TRUSTED_PROXY_TOKEN'],
        'X-Real-IP': '203.0.113.42', 'X-Forwarded-For': '198.51.100.99',
        'Origin': origin, 'User-Agent': 'FinCore-production-CI',
    }

    def call(path, payload=None, headers=None):
        request = Request(base + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', **(trusted if headers is None else headers)})
        try:
            response = urlopen(request, timeout=20)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            return response.status, json.loads(body) if body else None, response.headers

    assert call('/health', headers={})[0] == 200, 'Frontend health failed'
    assert call('/api/backend/users/me', headers={'X-Real-IP': '198.51.100.99'})[0] == 403, 'Untrusted ingress admitted'
    assert call('/api/backend/users/me', headers={**trusted, 'X-Real-IP': '203.0.113.1,198.51.100.1'})[0] == 400, 'IP list admitted'
    assert call('/api/backend/auth/confirm/resend', {'email': 'unknown@example.com'},
                headers={**trusted, 'Origin': 'https://foreign.example'})[0] == 403, 'Foreign Origin admitted'
    username = 'ci_' + uuid4().hex
    email, password = username + '@example.com', 'CiIntegration2026!'
    assert call('/api/backend/auth/register', {'username': username, 'email': email})[0] == 201, 'Registration failed'

    def wait_tokens(minimum):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            with urlopen(mailpit + '/api/v1/messages', timeout=5) as response:
                messages = json.load(response).get('messages', [])
            tokens = {}
            for message in messages:
                if not any(recipient['Address'] == email for recipient in message.get('To', [])):
                    continue
                with urlopen(mailpit + '/api/v1/message/' + message['ID'], timeout=5) as response:
                    detail = json.load(response)
                for link in re.findall(r'https?://[^\s<>"\']+', detail.get('Text', '')):
                    token = parse_qs(urlsplit(link).fragment).get('token', [None])[0]
                    if token:
                        tokens[message['ID']] = token
            if len(tokens) >= minimum:
                return tokens
            time.sleep(0.2)
        raise AssertionError('Outbox delivery did not reach Mailpit')

    first = wait_tokens(1)
    old_token = next(iter(first.values()))
    status, accepted, _ = call('/api/backend/auth/confirm/resend', {'email': email})
    assert status == 202, 'Resend failed'
    assert call('/api/backend/auth/confirm/resend', {'email': 'unknown@example.com'})[1] == accepted, 'Resend discloses account status'
    second = wait_tokens(2)
    new_token = next(token for message_id, token in second.items() if message_id not in first)
    assert call('/api/backend/auth/confirm', {'token': old_token, 'password': password})[0] == 400, 'Old confirmation still valid'
    assert call('/api/backend/auth/confirm', {'token': new_token, 'password': password})[0] == 204, 'New confirmation failed'
    status, body, headers = call('/api/backend/auth/login', {'username': username, 'password': password})
    assert status == 200 and body == {'authenticated': True}, 'Gateway login failed or exposed tokens'
    cookies = SimpleCookie()
    for value in headers.get_all('Set-Cookie', []):
        assert 'HttpOnly' in value and 'Secure' in value, 'Insecure auth cookie'
        cookies.load(value)
    assert {'fincore_access', 'fincore_refresh'} <= set(cookies), 'Missing session cookies'
    authenticated = {**trusted, 'Cookie': '; '.join(f'{key}={value.value}' for key, value in cookies.items())}
    assert call('/api/backend/users/me', headers=authenticated)[1]['username'] == username, 'Authenticated profile failed'
    assert call('/api/backend/wallets', {'name': 'CI wallet', 'currency': 'CAD'}, headers=authenticated)[0] == 201, 'Wallet creation failed'
    compose = ['docker', 'compose', '--env-file', '/dev/null', '-p', project]
    verify = """
import asyncio, os
from sqlalchemy import select
from backend.infrastructure.settings import get_settings
from backend.infrastructure.db.sqlalchemy.core.database import create_engine, create_session_factory
from backend.infrastructure.db.sqlalchemy.models import SqlAlchemySessionModel as Session, SqlAlchemyUserModel as User
async def main():
    engine = create_engine(get_settings())
    try:
        async with create_session_factory(engine)() as session:
            records = (await session.scalars(select(Session).join(User, User.id == Session.user_id)
                .where(User.username == os.environ['CI_SMOKE_USERNAME']))).all()
            assert len(records) == 1
            assert records[0].ip_address == '203.0.113.42'
            assert records[0].user_agent == 'FinCore-production-CI'
    finally:
        await engine.dispose()
asyncio.run(main())
"""
    subprocess.run(compose + ['exec', '-T', '-e', 'CI_SMOKE_USERNAME=' + username, 'api', 'python', '-'],
                   input=verify, text=True, check=True, capture_output=True)
    result = subprocess.run(compose + ['exec', '-T', 'maintenance', 'python', '-m', 'backend.bootstrap.cleanup', '--dry-run'],
                            text=True, check=True, capture_output=True)
    assert json.loads(result.stdout)['dry_run'] is True, 'Maintenance preview failed'
    print('Production Compose checks passed: ingress/IP, CSRF, email/resend/confirm/login, cookies, wallets and maintenance.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        # URLs, SMTP credentials and auth responses never enter CI failure logs.
        detail = str(exc) if isinstance(exc, AssertionError) else type(exc).__name__
        print(f'Production stack check failed ({detail}).', file=sys.stderr)
        raise SystemExit(1)
