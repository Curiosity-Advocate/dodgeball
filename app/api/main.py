from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.management import router as management_router
from app.api.read import router as read_router
from app.api.scoring import router as scoring_router
from app.api.ws import router as ws_router
from app.core.errors import AppError


def create_app() -> FastAPI:
    app = FastAPI(title="DodgeballPlus")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # v1.0: open; narrow to the client origin later
        allow_credentials=False,  # bearer tokens, not cookies
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(management_router)
    app.include_router(scoring_router)
    app.include_router(read_router)
    app.include_router(ws_router)
    _register_error_handlers(app)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _on_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.exception_handler(RequestValidationError)
    async def _on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": "Invalid request"}},
        )


app = create_app()
