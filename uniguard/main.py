from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import database as db
from .config import settings
from .arguss_client import (
    send_visit_to_arguss,
    ArgussConnectionError,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    yield


app = FastAPI(
    title="UniGuard API",
    version="1.0.1",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class VisitRequest(BaseModel):
    department: int = Field(ge=1, le=3)
    visitor_name: str = Field(min_length=1, max_length=120)
    visitor_reason: str = Field(default="", max_length=500)


@app.get("/")
async def root():
    return {
        "ok": True,
        "service": "UniGuard",
        "status": "running",
    }


@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "service": "UniGuard",
        "mode": settings.access_controller_mode,
        "arguss_configured": bool(
            settings.arguss_api_url
            and settings.arguss_service_token
        ),
    }


@app.post("/api/visits")
async def create_visit(data: VisitRequest):
    visitor_name = data.visitor_name.strip()
    visitor_reason = data.visitor_reason.strip()

    if not visitor_name:
        raise HTTPException(
            status_code=422,
            detail="El nombre del visitante es obligatorio.",
        )

    try:
        result = await send_visit_to_arguss(
            department=data.department,
            visitor_name=visitor_name,
            visitor_reason=visitor_reason,
        )

        db.log(
            "VISIT_SENT_TO_ARGUSS",
            {
                "department": data.department,
                "visitor_name": visitor_name,
                "visitor_reason": visitor_reason,
                "response": result,
            },
        )

        return {
            "ok": True,
            "visit": result,
        }

    except (ArgussConnectionError, ValueError) as error:
        raise HTTPException(
            status_code=502,
            detail=str(error),
        ) from error

    except Exception as error:
        db.log(
            "VISIT_SEND_UNEXPECTED_ERROR",
            {
                "department": data.department,
                "visitor_name": visitor_name,
                "error": str(error),
            },
        )

        raise HTTPException(
            status_code=500,
            detail="Ocurrió un error interno al registrar la visita.",
        ) from error
