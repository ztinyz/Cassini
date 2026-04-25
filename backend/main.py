"""FastAPI: AOI analysis via Google Earth Engine (optional)."""
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()
from app.gee_river import AnalyzeConfig, analyze_aoi, gee_is_ready

_origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
_origins = [o.strip() for o in _origins if o.strip()]

@asynccontextmanager
async def _lifespan(_: FastAPI):
    # Trigger EE init once
    gee_is_ready()
    yield


app = FastAPI(
    title="River morphology screening",
    version="0.1.0",
    lifespan=_lifespan,
    description="Sentinel-1/2 change screening via GEE. Not a legal finding.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    geometry: dict
    start_date: str = Field(
        description="Start date ISO (e.g. 2018-01-01T00:00:00Z)",
    )
    end_date: str = Field(description="End date (exclusive or inclusive range per client)")
    include_s1: bool = True
    z_threshold: float = 2.0
    s2_fusion_weight: float = 0.55
    s1_fusion_weight: float = 0.45
    max_area_km2: float = 2000.0


class HealthResponse(BaseModel):
    gee: bool
    gee_message: str


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    mock = os.environ.get("GEE_MOCK", "").lower() in ("1", "true", "yes")
    if mock:
        return HealthResponse(
            gee=False,
            gee_message="GEE_MOCK set; responses use sample polygons. Unset for real GEE.",
        )
    r = gee_is_ready()
    if r:
        return HealthResponse(
            gee=True,
            gee_message="GEE initialised. Run analysis for screening layers.",
        )
    return HealthResponse(
        gee=False,
        gee_message=(
            "GEE not available. Set GOOGLE_APPLICATION_CREDENTIALS, "
            "EARTHENGINE_PROJECT (or GEE_PROJECT), and earthengine authenticate; "
            "or GEE_MOCK=1 for a demo without credentials."
        ),
    )


@app.post("/api/analyze")
def analyze(
    body: AnalyzeRequest,
) -> JSONResponse:
    cfg = AnalyzeConfig(
        z_threshold=body.z_threshold,
        s1_fusion_weight=body.s1_fusion_weight,
        s2_fusion_weight=body.s2_fusion_weight,
        max_area_km2=body.max_area_km2,
    )
    out: dict[str, Any] = analyze_aoi(
        body.geometry,
        body.start_date,
        body.end_date,
        cfg=cfg,
        include_s1=body.include_s1,
    )
    return JSONResponse(content=out)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
