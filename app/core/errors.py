from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


ERROR_CODES = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    409: "TASK_ALREADY_SUBMITTED",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_SERVER_ERROR",
}


def register_error_handlers(app) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
        return _error_response(exc.status_code, ERROR_CODES.get(exc.status_code, "HTTP_ERROR"), message)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(422, "VALIDATION_ERROR", "请求参数校验失败", {"errors": _safe_errors(exc.errors())})

    @app.exception_handler(Exception)
    async def generic_exception_handler(_: Request, __: Exception) -> JSONResponse:
        return _error_response(500, "INTERNAL_SERVER_ERROR", "服务内部错误")


def _error_response(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def _safe_errors(errors: list[dict]) -> list[dict]:
    safe: list[dict] = []
    for error in errors:
        item = dict(error)
        if "ctx" in item:
            item["ctx"] = {key: str(value) for key, value in item["ctx"].items()}
        safe.append(jsonable_encoder(item))
    return safe
