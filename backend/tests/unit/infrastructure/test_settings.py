import pytest
from pydantic import ValidationError

from backend.infrastructure.settings import Settings, get_settings

URL = 'postgresql+asyncpg://test:test-secret@localhost:5432/fincore_test'


def test_settings_load_env_and_hide_database_secret(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', URL)
    monkeypatch.setenv('DATABASE_POOL_SIZE', '3')
    settings = Settings(_env_file=None)
    assert settings.database_url.get_secret_value() == URL
    assert settings.database_pool_size == 3
    assert 'test-secret' not in repr(settings)
    assert 'test-secret' not in settings.model_dump_json()


def test_env_overrides_dotenv(tmp_path, monkeypatch):
    path = tmp_path / '.env'
    path.write_text('DATABASE_URL=' + URL + '\nDATABASE_POOL_SIZE=2\nUNRELATED=value\n')
    monkeypatch.setenv('DATABASE_POOL_SIZE', '4')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    settings = Settings(_env_file=path)
    assert settings.database_pool_size == 4
    assert settings.database_url.get_secret_value() == URL


@pytest.mark.parametrize('url', ['invalid-url', 'postgresql://localhost/db', 'sqlite:///db', 'postgresql+asyncpg://localhost'])
def test_rejects_wrong_database_urls(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


@pytest.mark.parametrize(('field', 'value'), [('database_pool_size', 0), ('database_max_overflow', -1), ('database_pool_timeout', 0)])
def test_rejects_invalid_pool_settings(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=URL, **{field: value})


def test_missing_url_is_error(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_cache(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv('DATABASE_URL', URL)
    get_settings.cache_clear()
    try:
        assert get_settings() is get_settings()
    finally:
        get_settings.cache_clear()


def test_confirmation_ttl_defaults_and_env_override(monkeypatch):
    from datetime import timedelta

    default = Settings(_env_file=None, database_url=URL)
    assert default.verification_confirmation_ttl == timedelta(hours=1)
    monkeypatch.setenv('VERIFICATION_CONFIRMATION_TTL', 'PT15M')
    configured = Settings(_env_file=None, database_url=URL)
    assert configured.verification_confirmation_ttl == timedelta(minutes=15)


@pytest.mark.parametrize('value', ['PT0S', '-PT1H', 'invalid'])
def test_confirmation_ttl_rejects_nonpositive_or_invalid_value(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=URL, verification_confirmation_ttl=value)


def test_session_ttl_default_and_env_override(monkeypatch):
    from datetime import timedelta

    monkeypatch.delenv('SESSION_TTL', raising=False)
    assert Settings(_env_file=None, database_url=URL).session_ttl == timedelta(days=30)
    monkeypatch.setenv('SESSION_TTL', 'P7D')
    assert Settings(_env_file=None, database_url=URL).session_ttl == timedelta(days=7)


@pytest.mark.parametrize('value', ['PT0S', '-P1D', 'invalid'])
def test_session_ttl_must_be_positive(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=URL, session_ttl=value)


@pytest.mark.parametrize('url', [
    'http://localhost:6379', 'redis://', 'redis://localhost/-1',
    'redis://localhost/abc', 'redis://localhost:0/0', 'redis://localhost:99999/0',
    'redis://localhost/0?socket_timeout=0', 'redis://localhost/0#secret',
    'redis://[bad', 'redis://localhost/１２',
])
def test_invalid_redis_urls_are_rejected(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=URL, redis_url=url)


@pytest.mark.parametrize('field,value', [
    ('redis_connect_timeout', 0), ('redis_socket_timeout', -1),
    ('redis_socket_timeout', float('inf')), ('redis_max_connections', 0),
])
def test_invalid_redis_pool_settings_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=URL, **{field: value})


def test_redis_url_from_environment_hides_credentials(monkeypatch):
    url = 'rediss://user:redis-private-secret@localhost:6379/2'
    monkeypatch.setenv('REDIS_URL', url)
    settings = Settings(_env_file=None, database_url=URL)
    assert settings.redis_url.get_secret_value() == url
    assert 'redis-private-secret' not in repr(settings)
    assert 'redis-private-secret' not in settings.model_dump_json()


@pytest.mark.parametrize('field', [
    'login_rate_limit_ip_per_minute', 'login_rate_limit_username_per_minute',
    'register_rate_limit_ip_per_hour', 'register_rate_limit_email_per_hour',
    'transfer_rate_limit_user_per_minute', 'transfer_rate_limit_ip_per_minute',
])
@pytest.mark.parametrize('value', [0, -1, 2 ** 53])
def test_rate_limit_budgets_must_be_positive_safe_integers(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=URL, **{field: value})


def test_rate_limit_budgets_are_configurable_from_environment(monkeypatch):
    monkeypatch.setenv('LOGIN_RATE_LIMIT_USERNAME_PER_MINUTE', '4')
    monkeypatch.setenv('REGISTER_RATE_LIMIT_IP_PER_HOUR', '7')
    monkeypatch.setenv('TRANSFER_RATE_LIMIT_USER_PER_MINUTE', '8')
    settings = Settings(_env_file=None, database_url=URL)
    assert settings.login_rate_limit_username_per_minute == 4
    assert settings.register_rate_limit_ip_per_hour == 7
    assert settings.transfer_rate_limit_user_per_minute == 8
