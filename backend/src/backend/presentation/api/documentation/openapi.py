import json
from copy import deepcopy
from importlib.resources import files
from typing import Any, Literal

from fastapi import FastAPI

from backend.presentation.api.errors import ERROR_RESPONSES


Locale = Literal["ru", "en"]

OPERATIONS = {
    ('/v1/transfer-recipients/resolve', 'post'): 'resolve_wallet_recipient',
    ('/v1/transfers', 'post'): 'create_transfer',
    ('/v1/transfers/{transfer_id}', 'get'): 'get_transfer',
    ('/v1/transfers', 'get'): 'get_my_transfers',
    ('/v1/sandbox/top-ups', 'post'): 'create_sandbox_top_up',
    ('/v1/wallets/{wallet_id}/transactions', 'get'): 'get_wallet_transactions',
    ('/v1/users/me/transactions', 'get'): 'get_my_transactions',
    ('/v1/wallets/{wallet_id}/balance', 'get'): 'get_wallet_balance',
    ('/v1/users/me/balances', 'get'): 'get_my_balance_summary',
    ("/health", "get"): "health",
    ("/health/live", "get"): "health_live",
    ("/health/ready", "get"): "health_ready",
    ("/v1/wallets/{wallet_id}/freeze", "post"): "freeze_wallet",
    ("/v1/wallets/{wallet_id}/unfreeze", "post"): "unfreeze_wallet",
    ("/v1/auth/register", "post"): "register",
    ("/v1/auth/confirm/resend", "post"): "resend_confirmation",
    ("/v1/auth/confirm", "post"): "confirm",
    ("/v1/auth/login", "post"): "login",
    ("/v1/auth/refresh", "post"): "refresh",
    ("/v1/auth/logout", "post"): "logout",
    ("/v1/auth/change-password", "post"): "change_password",
    ("/v1/auth/password-reset/request", "post"): "request_password_reset",
    ("/v1/auth/password-reset/confirm", "post"): "confirm_password_reset",
    ("/v1/users/me", "get"): "get_current_user",
    ("/v1/users/me/sessions", "get"): "get_active_sessions",
    ("/v1/users/me/sessions", "delete"): "remove_all_sessions",
    ("/v1/users/me/sessions/{session_id}", "delete"): "remove_session",
    ("/v1/wallets", "post"): "create_wallet",
    ("/v1/wallets", "get"): "get_my_wallets",
    ("/v1/wallets/{wallet_id}", "get"): "get_wallet",
    ("/v1/wallets/{wallet_id}", "patch"): "rename_wallet",
    ("/v1/wallets/{wallet_id}/close", "post"): "close_wallet",
}

REQUEST_EXAMPLES = {
    'resolve_wallet_recipient': {'wallet_number': '00001234567890123456'},
    'create_transfer': {'sender_wallet_id': '7e416d74-e41e-4ce2-b0d2-4b4cf39ed598', 'receiver_wallet_id': '2a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'amount_minor': '10000', 'currency': 'USD'},
    'create_sandbox_top_up': {'wallet_id': '7e416d74-e41e-4ce2-b0d2-4b4cf39ed598', 'amount_minor': '50000', 'currency': 'USD'},
    "register": {"username": "alice", "email": "alice@example.com"},
    "resend_confirmation": {"email": "alice@example.com"},
    "confirm": {"token": "example-confirmation-token", "password": "ExamplePassword1!"},
    "login": {"username": "alice", "password": "ExamplePassword1!"},
    "refresh": {"refresh_token": "example-refresh-token"},
    "logout": {"refresh_token": "example-refresh-token"},
    "change_password": {"current_password": "ExamplePassword1!", "new_password": "NewExamplePassword2!"},
    "request_password_reset": {"email": "alice@example.com"},
    "confirm_password_reset": {"token": "example-password-reset-token"},
    "create_wallet": {"name": "Main", "currency": "USD"},
    "rename_wallet": {"name": "Savings"},
}

TOKEN_EXAMPLE = {"access_token": "example-access-token", "refresh_token": "example-refresh-token"}
WALLET_EXAMPLE = {
    "id": "7e416d74-e41e-4ce2-b0d2-4b4cf39ed598",
    "user_id": "91e75e1a-bc83-4cb4-a47c-cb08585e7dd0",
    "name": "Main", "balance_minor": "12345", "number": "00001234567890123456",
    "currency": "USD", "status": "active",
    "created_at": "2026-11-01T12:00:00Z", "updated_at": "2026-11-01T12:00:00Z",
}
SUCCESS_EXAMPLES = {
    'resolve_wallet_recipient': {'wallet_id': '2a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'number': '00001234567890123456', 'currency': 'CAD', 'owner': 'bobuser'},
    'health_live': {'status': 'ok'},
    'health_ready': {'status': 'ok', 'checks': {'postgres': 'ok', 'redis': 'ok'}},
    'create_transfer': {'transfer_id': '3a416d74-e41e-4ce2-b0d2-4b4cf39ed599'},
    'create_sandbox_top_up': {'top_up_id': '3a416d74-e41e-4ce2-b0d2-4b4cf39ed599'},
    'get_transfer': {'id': '3a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'sender_wallet_id': '7e416d74-e41e-4ce2-b0d2-4b4cf39ed598', 'receiver_wallet_id': '2a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'amount_minor': '10000', 'currency': 'USD', 'status': 'completed', 'direction': 'outgoing', 'created_at': '2026-11-12T12:00:00Z', 'completed_at': '2026-11-12T12:00:00Z', 'rejection_code': None},
    'get_my_transfers': {'items': [{'id': '3a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'sender_wallet_id': '7e416d74-e41e-4ce2-b0d2-4b4cf39ed598', 'receiver_wallet_id': '2a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'amount_minor': '10000', 'currency': 'USD', 'status': 'completed', 'direction': 'outgoing', 'created_at': '2026-11-12T12:00:00Z', 'completed_at': '2026-11-12T12:00:00Z', 'rejection_code': None}], 'next_cursor': None},
    'get_wallet_transactions': {'items': [{'id': '3a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'source_type': 'p2p_transfer', 'source_id': '3a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'sender_wallet_id': '7e416d74-e41e-4ce2-b0d2-4b4cf39ed598', 'receiver_wallet_id': '2a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'amount_minor': '10000', 'currency': 'USD', 'direction': 'outgoing', 'posted_at': '2026-11-12T12:00:00Z', 'wallet_id': '7e416d74-e41e-4ce2-b0d2-4b4cf39ed598', 'counterparty_wallet_id': '2a416d74-e41e-4ce2-b0d2-4b4cf39ed599'}], 'next_cursor': None},
    'get_my_transactions': {'items': [{'id': '3a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'source_type': 'p2p_transfer', 'source_id': '3a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'sender_wallet_id': '7e416d74-e41e-4ce2-b0d2-4b4cf39ed598', 'receiver_wallet_id': '2a416d74-e41e-4ce2-b0d2-4b4cf39ed599', 'amount_minor': '10000', 'currency': 'USD', 'direction': 'outgoing', 'posted_at': '2026-11-12T12:00:00Z'}], 'next_cursor': None},
    'get_wallet_balance': {'wallet_id': '7e416d74-e41e-4ce2-b0d2-4b4cf39ed598', 'currency': 'USD', 'posted_minor': '40000', 'available_minor': '40000', 'spendable_minor': '40000', 'version': '2', 'updated_at': '2026-11-12T12:00:00Z', 'as_of': '2026-11-12T12:00:00Z'},
    'get_my_balance_summary': {'totals': [{'currency': 'USD', 'posted_minor': '40000', 'available_minor': '40000', 'spendable_minor': '40000'}], 'as_of': '2026-11-12T12:00:00Z'},
    "get_wallet": WALLET_EXAMPLE,
    "get_my_wallets": [WALLET_EXAMPLE],
    "create_wallet": {"wallet_id": "7e416d74-e41e-4ce2-b0d2-4b4cf39ed598"},
    "health": {"status": "ok"},
    "register": {"user_id": "91e75e1a-bc83-4cb4-a47c-cb08585e7dd0"},
    "resend_confirmation": {"message": "If the account is awaiting confirmation, a new confirmation email will be sent."},
    "login": TOKEN_EXAMPLE,
    "refresh": TOKEN_EXAMPLE,
    "request_password_reset": {"message": "If the account is eligible, a password reset email will be sent."},
    "confirm_password_reset": {"password": "ExampleGenerated1!"},
    "get_current_user": {
        "id": "91e75e1a-bc83-4cb4-a47c-cb08585e7dd0",
        "username": "alice", "email": "alice@example.com", "created_at": "2026-11-01T12:00:00Z",
    },
    "get_active_sessions": [{
        "id": "075c5cfe-dabb-45d6-9b83-6d06be719316",
        "ip_address": "192.0.2.10", "user_agent": "Example Browser",
        "created_at": "2026-11-01T12:00:00Z", "expires_at": "2026-12-01T12:00:00Z",
        "last_ip_address": None, "last_user_agent": None, "last_used_at": None,
    }],
}

ERROR_EXAMPLES = {
    'resend_confirmation': {'400': ['http_error'], '422': ['request_validation_error'], '429': ['http_error'], '503': ['rate_limiter_unavailable']},
    'resolve_wallet_recipient': {'400': ['http_error'], '401': ['http_error', 'invalid_access_token', 'access_token_expired'], '403': ['user_inactive'], '404': ['user_not_found', 'wallet_not_found'], '422': ['request_validation_error'], '429': ['http_error'], '503': ['rate_limiter_unavailable']},
    'create_transfer': {'401': ['http_error', 'invalid_access_token', 'access_token_expired'], '403': ['user_inactive'], '404': ['user_not_found', 'wallet_not_found'], '409': ['idempotency_conflict', 'idempotency_in_progress'], '422': ['request_validation_error', 'insufficient_funds', 'transfer_currency_mismatch', 'transfer_limit_exceeded', 'same_wallet_transfer'], '500': ['wallet_accounting_state_error']},
    'get_transfer': {'401': ['http_error', 'invalid_access_token', 'access_token_expired'], '403': ['user_inactive'], '404': ['user_not_found', 'transfer_not_found'], '422': ['request_validation_error']},
    'get_my_transfers': {'401': ['http_error', 'invalid_access_token', 'access_token_expired'], '403': ['user_inactive'], '404': ['user_not_found'], '422': ['request_validation_error', 'invalid_cursor']},
    'create_sandbox_top_up': {'401': ['http_error', 'invalid_access_token', 'access_token_expired'], '403': ['user_inactive', 'sandbox_disabled', 'sandbox_operator_required'], '404': ['user_not_found', 'wallet_not_found'], '409': ['idempotency_conflict', 'idempotency_in_progress'], '422': ['request_validation_error'], '500': ['wallet_accounting_state_error', 'sandbox_funding_account_error']},
    'get_wallet_transactions': {'401': ['http_error', 'invalid_access_token', 'access_token_expired'], '403': ['user_inactive'], '404': ['user_not_found', 'wallet_not_found'], '422': ['request_validation_error', 'invalid_cursor']},
    'get_my_transactions': {'401': ['http_error', 'invalid_access_token', 'access_token_expired'], '403': ['user_inactive'], '404': ['user_not_found'], '422': ['request_validation_error', 'invalid_cursor']},
    'get_wallet_balance': {'401': ['http_error', 'invalid_access_token', 'access_token_expired'], '403': ['user_inactive'], '404': ['user_not_found', 'wallet_not_found'], '422': ['request_validation_error'], '500': ['wallet_accounting_state_error']},
    'get_my_balance_summary': {'401': ['http_error', 'invalid_access_token', 'access_token_expired'], '403': ['user_inactive'], '404': ['user_not_found'], '422': ['request_validation_error'], '500': ['wallet_accounting_state_error']},
    "get_wallet": {
        "401": ["http_error", "invalid_access_token", "access_token_expired"],
        "403": ["user_inactive"], "404": ["user_not_found", "wallet_not_found"],
        "422": ["request_validation_error"], "500": ["wallet_accounting_state_error"],
    },
    "get_my_wallets": {
        "401": ["http_error", "invalid_access_token", "access_token_expired"],
        "403": ["user_inactive"], "404": ["user_not_found"],
        "422": ["request_validation_error"], "500": ["wallet_accounting_state_error"],
    },
    "create_wallet": {
        "401": ["http_error", "invalid_access_token", "access_token_expired"],
        "403": ["user_inactive"], "404": ["user_not_found"],
        "422": ["request_validation_error", "invalid_wallet_name"], "503": ["wallet_number_unavailable"],
    },
    "rename_wallet": {
        "401": ["http_error", "invalid_access_token", "access_token_expired"],
        "403": ["user_inactive"], "404": ["user_not_found", "wallet_not_found"],
        "409": ["wallet_closed"], "422": ["request_validation_error", "invalid_wallet_name"],
    },
    "close_wallet": {
        "401": ["http_error", "invalid_access_token", "access_token_expired"],
        "403": ["user_inactive"], "404": ["user_not_found", "wallet_not_found"],
        "409": ["wallet_balance_not_zero"], "422": ["request_validation_error"],
        "500": ["wallet_accounting_state_error"],
    },
    "get_current_user": {
        "401": ["http_error", "invalid_access_token", "access_token_expired"],
        "403": ["user_inactive"], "404": ["user_not_found"],
    },
    "get_active_sessions": {
        "401": ["http_error", "invalid_access_token", "access_token_expired"],
        "403": ["user_inactive"], "404": ["user_not_found"],
    },
    "remove_all_sessions": {
        "401": ["http_error", "invalid_access_token", "access_token_expired"],
        "403": ["user_inactive"], "404": ["user_not_found"],
    },
    "remove_session": {
        "401": ["http_error", "invalid_access_token", "access_token_expired"],
        "403": ["user_inactive"], "404": ["user_not_found", "session_not_found"],
        "422": ["request_validation_error"],
    },
    "change_password": {
        "401": ["invalid_credentials", "invalid_access_token", "access_token_expired", "http_error"],
        "403": ["user_inactive"], "422": ["request_validation_error", "invalid_password"],
    },
    "request_password_reset": {
        "400": ["http_error"], "422": ["request_validation_error"], "429": ["http_error"],
        "503": ["rate_limiter_unavailable"],
    },
    "confirm_password_reset": {
        "400": ["invalid_password_reset_token", "http_error"],
        "422": ["request_validation_error"], "429": ["http_error"],
        "503": ["rate_limiter_unavailable"],
    },
    "login": {
        "400": ["http_error"], "401": ["invalid_credentials"],
        "403": ["user_inactive"], "422": ["request_validation_error"],
    },
    "register": {
        "409": ["email_already_exists", "username_already_exists"],
        "422": ["request_validation_error"],
    },
    "refresh": {
        "400": ["http_error"], "401": ["invalid_refresh_token"],
        "403": ["user_inactive"], "422": ["request_validation_error"],
    },
    "logout": {"422": ["request_validation_error"]},
    "confirm": {
        "400": ["invalid_confirmation_token", "confirmation_token_expired", "confirmation_token_used"],
        "404": ["user_not_found"], "409": ["user_not_pending_confirmation"],
        "422": ["request_validation_error", "invalid_password"],
    },
}


for name in ('freeze_wallet', 'unfreeze_wallet'):
    ERROR_EXAMPLES[name] = {
        '401': ['http_error', 'invalid_access_token', 'access_token_expired'],
        '403': ['user_inactive'], '404': ['user_not_found', 'wallet_not_found'],
        '409': ['wallet_closed'], '422': ['request_validation_error'],
        '500': ['wallet_accounting_state_error'],
    }

for operation in ('login', 'register', 'create_transfer'):
    ERROR_EXAMPLES[operation].update({
        '400': ['http_error'], '429': ['http_error'], '503': ['rate_limiter_unavailable'],
    })


def error_example(code: str, operation: str, status: str = "") -> dict[str, Any]:
    messages = {entry[1]: entry[2] for entry in ERROR_RESPONSES.values()}
    messages.update({"request_validation_error": "Invalid request", "http_error": "Cannot determine client IP"})
    if status == "429":
        messages["http_error"] = "Too many requests"
    elif operation in {
        "change_password", "get_current_user", "get_active_sessions", "remove_all_sessions", "remove_session",
        "create_wallet", "rename_wallet", "close_wallet", "get_wallet", "get_my_wallets",
    }:
        messages["http_error"] = "Not authenticated"
    if status == "401":
        messages["http_error"] = "Not authenticated"
    errors = []
    if code == "request_validation_error":
        field = {
            "confirm": "token", "refresh": "refresh_token", "logout": "refresh_token",
            "request_password_reset": "email", "resend_confirmation": "email", "confirm_password_reset": "token", "change_password": "new_password",
            "create_wallet": "name", "rename_wallet": "name", "create_transfer": "amount_minor", "create_sandbox_top_up": "amount_minor",
            "resolve_wallet_recipient": "wallet_number",
        }.get(operation, "username")
        errors = [{"loc": ["body", field], "message": "Field required", "type": "missing"}]
        if operation == "remove_session":
            errors = [{"loc": ["path", "session_id"], "message": "Input should be a valid UUID", "type": "uuid_parsing"}]
        elif operation in {"close_wallet", "get_wallet", "freeze_wallet", "unfreeze_wallet"}:
            errors = [{"loc": ["path", "wallet_id"], "message": "Input should be a valid UUID", "type": "uuid_parsing"}]
        elif operation in {"get_my_transfers", "get_my_transactions", "get_wallet_transactions", "get_my_balance_summary"}:
            errors = [{"loc": ["query", "limit"], "message": "Invalid query parameters", "type": "value_error"}]
        elif operation == "get_wallet_balance":
            errors = [{"loc": ["path", "wallet_id"], "message": "Input should be a valid UUID", "type": "uuid_parsing"}]
        elif operation == "get_transfer":
            errors = [{"loc": ["path", "transfer_id"], "message": "Input should be a valid UUID", "type": "uuid_parsing"}]
        elif operation == "get_my_wallets":
            errors = [{"loc": ["query", "currency"], "message": "Input should be 'USD', 'EUR', 'JPY', 'CHF', 'GBP', 'UZS', 'CAD' or 'RUB'", "type": "enum"}]
    elif code == "invalid_password":
        errors = [{"loc": ["body", "password"], "message": "Password must contain digit", "type": code}]
    return {"detail": {"code": code, "message": messages[code], "errors": errors}}


class LocalizedOpenAPI:
    def __init__(self, app: FastAPI) -> None:
        # Capture FastAPI's generator before overriding app.openapi. Its cache stays untranslated.
        self._base_openapi = app.openapi
        self._schemas: dict[Locale, tuple[dict[str, Any], dict[str, Any]]] = {}

    def schema(self, locale: Locale) -> dict[str, Any]:
        base = self._base_openapi()
        cached = self._schemas.get(locale)
        if cached is not None and cached[0] is base:
            return cached[1]
        directory = files(__package__).joinpath("content", locale)
        translations = json.loads(directory.joinpath("metadata.json").read_text(encoding="utf-8"))
        schema = deepcopy(base)
        schema["info"]["description"] = directory.joinpath("overview.md").read_text(encoding="utf-8")
        schema["info"]["x-language"] = locale
        schema["tags"] = translations["tags"]

        for (path, method), name in OPERATIONS.items():
            operation = schema["paths"][path][method]
            text = translations["operations"][name]
            operation["summary"] = text["summary"]
            operation["description"] = directory.joinpath(f"{name}.md").read_text(encoding="utf-8")
            if path.startswith(("/v1/wallets", "/v1/transfer-recipients/")):
                operation["tags"] = ["wallet"]
            elif path.startswith("/v1/transfers"):
                operation["tags"] = ["transfers"]
            elif path.startswith("/v1/sandbox"):
                operation["tags"] = ["sandbox"]
            else:
                operation["tags"] = ["users" if path.startswith("/v1/users/") else "health" if name in {"health", "health_live", "health_ready"} else "auth"]
            for parameter in operation.get("parameters", []):
                if parameter["name"] in text.get("parameters", {}):
                    parameter["description"] = text["parameters"][parameter["name"]]
            if name in REQUEST_EXAMPLES:
                operation["requestBody"]["description"] = translations["request_body"]
                operation["requestBody"]["content"]["application/json"]["example"] = deepcopy(REQUEST_EXAMPLES[name])
            for status, response in operation["responses"].items():
                response["description"] = text["responses"][status]
                if status in ERROR_EXAMPLES.get(name, {}):
                    response["content"]["application/json"]["examples"] = {
                        code: {"value": error_example(code, name, status)} for code in ERROR_EXAMPLES[name][status]
                    }
                elif name == 'health_ready' and status == '503':
                    response['content']['application/json']['example'] = {
                        'status': 'unavailable', 'checks': {'postgres': 'unavailable', 'redis': 'unavailable'},
                    }
                elif name in SUCCESS_EXAMPLES:
                    response["content"]["application/json"]["example"] = deepcopy(SUCCESS_EXAMPLES[name])

        for name, text in translations["schemas"].items():
            model = schema["components"]["schemas"][name]
            model["title"] = text["title"]
            model["description"] = text["description"]
            for field, field_text in text["fields"].items():
                model["properties"][field].update(field_text)
        self._schemas[locale] = (base, schema)
        return schema
