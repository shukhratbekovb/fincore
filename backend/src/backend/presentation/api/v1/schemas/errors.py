from pydantic import BaseModel, Field


class ValidationIssue(BaseModel):
    loc: list[str | int]
    message: str
    type: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    errors: list[ValidationIssue] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    detail: ErrorDetail
