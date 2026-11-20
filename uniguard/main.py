
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import database as db
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
    version="1.0.0",
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
        "mode": "SIMULATED",
        "arguss_configured": True,
    }


@app.post("/api/visits")
async def create_visit(data: VisitRequest):
    try:
        result = await send_visit_to_arguss(
            department=data.department,
            visitor_name=data.visitor_name.strip(),
            visitor_reason=data.visitor_reason.strip(),
        )

        db.log(
            "VISIT_SENT_TO_ARGUSS",
            {
                "department": data.department,
                "visitor_name": data.visitor_name,
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
        )
