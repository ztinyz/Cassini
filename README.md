# River change screening (Sentinel-1/2, GEE)

Web UI + API: draw an AOI, run a monthly S2 (MNDWI) and optional S1 (VV, dB) time series in Google Earth Engine, compare the **recent** months to a **baseline** (first ~65% of months) per pixel, and highlight `|Z| >= threshold` (default 2) as a vector layer on the map.

This is **screening only**; it does not prove or disprove illegal activity.

## Prerequisites

- Python 3.11+ with `pip install -r backend/requirements.txt` from `backend/`
- Node 18+ for the Vite app in `web/`
- A Google Cloud project with Earth Engine access; service or user auth per [Earth Engine Python](https://developers.google.com/earth-engine/guides/python_install)

## Environment (backend)

- `EARTHENGINE_PROJECT` or `GEE_PROJECT`: GEE-registered project ID (required for most setups)
- `GOOGLE_APPLICATION_CREDENTIALS`: path to a JSON key with EE access, **or** run `earthengine authenticate` and use a supported default credential flow
- `GEE_MOCK=1`: return demo polygons with no GEE (for UI testing)
- `CORS_ORIGINS`: optional comma list (default: `http://localhost:5173,http://127.0.0.1:5173`)

## Run

From `backend/`: `uvicorn main:app --reload --port 8000`

From `web/`: `npm install` then `npm run dev` — the dev server proxies `/api` to port 8000.

Open the printed URL, adjust dates (need several months, default range is ~6 years), optionally toggle Sentinel-1 fusion, then **Run screening**.

**Phase B (explanation):** with “Phase B: S2 before/after previews” enabled (default), `POST /api/analyze` also returns `explanation`: human-readable baseline/recent date ranges, a short summary of the Z-score logic, and two **S2 true-color median** thumbnail URLs (GEE `getThumbURL`) for the baseline and recent windows. Uncheck to skip extra GEE work. Previews are skipped for AOIs over ~2500 km².

## Project layout

- [backend/main.py](backend/main.py) — FastAPI, `/api/health`, `POST /api/analyze`
- [backend/app/gee_river.py](backend/app/gee_river.py) — GEE MNDWI/S1 stacks, z-scores, `reduceToVectors`
- [web/src/App.tsx](web/src/App.tsx) — MapLibre + AOI draw + result layer
- [docs/DATASETS.md](docs/DATASETS.md) — public datasets and how to use them
