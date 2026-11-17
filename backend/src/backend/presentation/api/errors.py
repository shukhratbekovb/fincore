from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from backend.application.auth.errors import (
    AccessTokenExpiredError,
    EmailAlreadyExistError,
    InvalidAccessTokenError,
    InvalidCredentialsError,
    InvalidPasswordResetTokenError,
    UserInactiveError,
    UsernameAlreadyExistError,
)
from backend.application.user.errors import UserNotFoundError
from backend.application.session.errors import SessionNotFoundError
from backend.application.verification.errors import VerificationChallengeNotFoundError
from backend.application.wallet.errors import (
    WalletNotFoundError,
    WalletBalanceNotZeroError,
    WalletNumberAlreadyExistsError,
    WalletAccountingStateError,
)
from backend.domain.session.errors import InvalidRefreshTokenError
from backend.domain.user.errors import (
    InvalidEmailError,
    InvalidPasswordError,
    InvalidUsernameError,
    UserNotPendingConfirmationError,
)
from backend.domain.verification.errors import (
    VerificationChallengeAlreadyUsedError,
    VerificationChallengeExpiredError,
    VerificationChallengePurposeMismatchError,
)
from backend.domain.wallet.errors import InvalidWalletNameError, WalletClosedError
from backend.presentation.api.v1.schemas.errors import ErrorDetail, ErrorResponse, ValidationIssue
from backend.application.transfer.errors import TransferNotFoundError, TransferCurrencyMismatchError, TransferLimitExceededError, InvalidTransferFilterError
from backend.application.history.errors import InvalidTransactionFilterError
from backend.application.share.errors import InvalidCursorError, InvalidPaginationError, RateLimiterUnavailableError
from backend.application.idempotency.errors import InvalidIdempotencyKeyError, IdempotencyConflictError, IdempotencyInProgressError
from backend.application.sandbox_top_up.errors import (
    SandboxDisabledError, SandboxOperatorRequiredError, SandboxFundingAccountError,
    SandboxTopUpCurrencyMismatchError, SandboxTopUpLimitExceededError,
)
from backend.domain.transfer.errors import SameWalletTransferError, InvalidTransferAmountError
from backend.domain.sandbox_top_up.errors import InvalidSandboxTopUpAmountError
from backend.domain.wallet.errors import WalletNotActiveError
from backend.domain.wallet_balance.errors import InsufficientFundsError, WalletBalanceOverflowError
from backend.domain.ledger_account.errors import LedgerAccountClosedError


# Known errors have stable responses. Unexpected failures remain plain HTTP 500.
ERROR_RESPONSES: dict[type[Exception], tuple[int, str, str]] = {
    RateLimiterUnavailableError: (503, "rate_limiter_unavailable", "Request limit service is temporarily unavailable"),
    TransferNotFoundError: (404, "transfer_not_found", "Transfer not found"),
    TransferCurrencyMismatchError: (422, "transfer_currency_mismatch", "Wallet currencies must match the command"),
    TransferLimitExceededError: (422, "transfer_limit_exceeded", "Transfer amount exceeds the configured limit"),
    InvalidTransferFilterError: (422, "invalid_transfer_filter", "Invalid transfer filters"),
    InvalidTransactionFilterError: (422, "invalid_transaction_filter", "Invalid transaction filters"),
    InvalidCursorError: (422, "invalid_cursor", "Invalid cursor or query context"),
    InvalidPaginationError: (422, "invalid_pagination", "Invalid page size"),
    InvalidIdempotencyKeyError: (422, "invalid_idempotency_key", "Invalid Idempotency-Key"),
    IdempotencyConflictError: (409, "idempotency_conflict", "Key was used with a different payload"),
    IdempotencyInProgressError: (409, "idempotency_in_progress", "Request is in progress; retry with the same key"),
    SandboxDisabledError: (403, "sandbox_disabled", "Sandbox funding is disabled"),
    SandboxOperatorRequiredError: (403, "sandbox_operator_required", "Sandbox operator permission is required"),
    SandboxFundingAccountError: (500, "sandbox_funding_account_error", "System funding account is unavailable"),
    SandboxTopUpCurrencyMismatchError: (422, "top_up_currency_mismatch", "Wallet currency must match the command"),
    SandboxTopUpLimitExceededError: (422, "top_up_limit_exceeded", "Top-up amount exceeds the configured limit"),
    SameWalletTransferError: (422, "same_wallet_transfer", "Sender and receiver wallets must be different"),
    InvalidTransferAmountError: (422, "invalid_transfer_amount", "Invalid transfer amount"),
    InvalidSandboxTopUpAmountError: (422, "invalid_top_up_amount", "Invalid top-up amount"),
    WalletNotActiveError: (409, "wallet_not_active", "Wallet does not allow money operations"),
    InsufficientFundsError: (422, "insufficient_funds", "Insufficient available funds"),
    WalletBalanceOverflowError: (422, "wallet_balance_overflow", "Wallet balance or version limit exceeded"),
    LedgerAccountClosedError: (409, "ledger_account_closed", "Ledger account is closed"),
    InvalidPasswordResetTokenError: (400, "invalid_password_reset_token", "Invalid or expired password reset token"),
    InvalidUsernameError: (422, "invalid_username", "Invalid username"),
    InvalidPasswordError: (422, "invalid_password", "Invalid password"),
    InvalidEmailError: (422, "invalid_email", "Invalid email"),
    InvalidCredentialsError: (401, "invalid_credentials", "Invalid username or password"),
    UserInactiveError: (403, "user_inactive", "User is inactive"),
    EmailAlreadyExistError: (409, "email_already_exists", "Email is already registered"),
    UsernameAlreadyExistError: (409, "username_already_exists", "Username is already registered"),
    InvalidRefreshTokenError: (401, "invalid_refresh_token", "Invalid or expired refresh token"),
    InvalidAccessTokenError: (401, "invalid_access_token", "Invalid access token"),
    AccessTokenExpiredError: (401, "access_token_expired", "Access token has expired"),
    UserNotFoundError: (404, "user_not_found", "User not found"),
    SessionNotFoundError: (404, "session_not_found", "Session not found"),
    WalletNotFoundError: (404, "wallet_not_found", "Wallet not found"),
    WalletBalanceNotZeroError: (409, "wallet_balance_not_zero", "Wallet balance must be zero before closing"),
    WalletClosedError: (409, "wallet_closed", "Wallet is closed"),
    InvalidWalletNameError: (422, "invalid_wallet_name", "Invalid wallet name"),
    WalletNumberAlreadyExistsError: (503, "wallet_number_unavailable", "Could not allocate a unique wallet number"),
    WalletAccountingStateError: (500, "wallet_accounting_state_error", "Wallet accounting state is inconsistent"),
    VerificationChallengeNotFoundError: (400, "invalid_confirmation_token", "Invalid confirmation token"),
    VerificationChallengeExpiredError: (400, "confirmation_token_expired", "Confirmation token has expired"),
    VerificationChallengeAlreadyUsedError: (400, "confirmation_token_used", "Confirmation token has already been used"),
    VerificationChallengePurposeMismatchError: (400, "invalid_confirmation_token", "Invalid confirmation token"),
    UserNotPendingConfirmationError: (409, "user_not_pending_confirmation", "User is not awaiting confirmation"),
}


async def handle_expected_error(request: Request, exc: Exception) -> JSONResponse:
    # MRO lookup also handles subclasses such as RefreshTokenReuseError.
    status_code, code, message = next(
        ERROR_RESPONSES[cls] for cls in type(exc).__mro__ if cls in ERROR_RESPONSES
    )
    errors = []
    if isinstance(exc, (InvalidUsernameError, InvalidPasswordError)):
        field = "username" if isinstance(exc, InvalidUsernameError) else "password"
        errors = [ValidationIssue(loc=["body", field], message=error, type=code) for error in exc.errors]
    response = ErrorResponse(detail=ErrorDetail(code=code, message=message, errors=errors))
    return JSONResponse(status_code=status_code, content=response.model_dump())


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Do not reflect `input` or `ctx`: they can contain passwords and tokens.
    response = ErrorResponse(detail=ErrorDetail(
        code="request_validation_error",
        message="Invalid request",
        errors=[ValidationIssue(loc=list(error["loc"]), message=error["msg"], type=error["type"])
                for error in exc.errors()],
    ))
    return JSONResponse(status_code=422, content=response.model_dump())


async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
    response = ErrorResponse(detail=ErrorDetail(code="http_error", message=str(exc.detail)))
    return JSONResponse(status_code=exc.status_code, content=response.model_dump(), headers=exc.headers)


def register_exception_handlers(app: FastAPI) -> None:
    for exception_type in ERROR_RESPONSES:
        app.add_exception_handler(exception_type, handle_expected_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(HTTPException, handle_http_error)
