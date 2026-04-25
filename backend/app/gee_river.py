"""
GEE: monthly S2 MNDWI + optional S1 VV (dB) time series, z-score (recent vs
baseline) per pixel, vectorize |z| >= z_threshold. Mock if GEE unavailable.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
from dateutil import parser
from dateutil.relativedelta import relativedelta

try:
    import ee
except Exception:  # noqa: S110
    ee = None  # type: ignore

try:
    from shapely.geometry import Point, box, mapping, shape
except Exception:  # noqa: S110
    Point = None  # type: ignore[assignment, misc]
    box = None
    mapping = None
    shape = None


@dataclass
class AnalyzeConfig:
    z_threshold: float = 2.0
    s2_scale_m: int = 50
    s1_fusion_weight: float = 0.45
    s2_fusion_weight: float = 0.55
    max_area_km2: float = 2000.0
    baseline_fraction: float = 0.65
    min_months: int = 4


_ee_ok: Optional[bool] = None


def _project_id_from_service_account_json() -> str:
    """If GOOGLE_APPLICATION_CREDENTIALS points to a key file, use its project_id."""
    p = (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or "").strip().strip('"')
    if not p or not os.path.isfile(p):
        return ""
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return (d.get("project_id") or "").strip()
    except OSError:
        return ""


def _try_init_ee() -> bool:
    if ee is None:
        return False
    project = (
        os.environ.get("EARTHENGINE_PROJECT")
        or os.environ.get("GEE_PROJECT")
        or _project_id_from_service_account_json()
        or ""
    ).strip()
    try:
        if project:
            ee.Authenticate(quiet=True)
    except Exception:
        pass
    try:
        if project:
            ee.Initialize(project=project)
        else:
            ee.Initialize()
        return True
    except Exception:
        try:
            ee.Initialize()
            return True
        except Exception:  # noqa: S110
            return False


def gee_is_ready() -> bool:
    global _ee_ok
    if _ee_ok is not None:
        return _ee_ok
    if os.environ.get("GEE_MOCK", "").lower() in ("1", "true", "yes"):
        _ee_ok = False
        return _ee_ok
    _ee_ok = _try_init_ee()
    return _ee_ok


def _mndwi_s2_one_band(image: "ee.Image") -> "ee.Image":
    """Single-band mndwi so all scenes in a month share identical band types for median()."""
    qa = image.select("QA60")
    m = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
    img = image.updateMask(m).divide(10000.0)
    return img.normalizedDifference(["B3", "B11"]).rename("mndwi")


def _s1_vv_to_db(image: "ee.Image") -> "ee.Image":
    lin = image.select("VV").max(1e-6)
    return lin.log10().multiply(10.0).rename("vv_db").copyProperties(
        image, ["system:time_start", "system:time_end"]
    )


def _n_months_between(start: str, end: str) -> int:
    t0 = parser.isoparse(start)
    t1 = parser.isoparse(end)
    n = 0
    t = t0.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    t_end = t1
    while t <= t_end and n < 200:
        n += 1
        t = t + relativedelta(months=1)
    return n


def _z_from_stack(
    stack: "ee.Image", n_baseline: int, n_total: int, out_name: str, ee_mod
) -> "ee.Image":
    b_all = stack.bandNames()
    b_base = b_all.slice(0, n_baseline)
    b_rec = b_all.slice(n_baseline, n_total)
    i_b = stack.select(b_base)
    m = i_b.reduce(ee_mod.Reducer.mean())
    s = i_b.reduce(ee_mod.Reducer.stdDev()).max(0.01)
    r_m = stack.select(b_rec).reduce(ee_mod.Reducer.mean())
    return r_m.subtract(m).divide(s).rename(out_name)


def _s2_one_month(geom, t0: "ee.ComputedObject", i: "ee.ComputedObject") -> "ee.Image":
    m = t0.advance(i, "month")
    return (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geom)
        .filterDate(m, m.advance(1, "month"))
        .map(_mndwi_s2_one_band)
        .median()
    )


def _s1_one_month(
    s1c: "ee.ImageCollection", t0, i: "ee.ComputedObject"
) -> "ee.Image":
    m = t0.advance(i, "month")
    c = s1c.filterDate(m, m.advance(1, "month"))
    return c.map(_s1_vv_to_db).median().select("vv_db")


def _monthly_s2_to_bands(geom, start: str, n_m: int) -> "ee.Image" | None:
    assert ee is not None
    t0 = ee.Date(start)
    n_m = max(0, n_m)
    if n_m < 2:
        return None
    s2_images = (
        ee.ImageCollection(ee.List.sequence(0, n_m - 1).map(lambda i: _s2_one_month(geom, t0, i)))  # type: ignore[arg-type, misc]
    )
    return s2_images.toBands()


def _monthly_s1_to_bands(geom, start: str, n_m: int) -> "ee.Image" | None:
    assert ee is not None
    t0 = ee.Date(start)
    s1b = (
        ee.ImageCollection("COPERNICUS/S1_GRD")
        .filterBounds(geom)
        .filter(ee.Filter.listContains("transmitterReceiverPolarisation", "VV"))
        .select("VV")
    )
    s1_images = (
        ee.ImageCollection(ee.List.sequence(0, n_m - 1).map(lambda i: _s1_one_month(s1b, t0, i)))  # type: ignore[arg-type, misc]
    )
    return s1_images.toBands()


def _fused_z(
    s2b: "ee.Image", s1b: "ee.Image", n: int, cfg: AnalyzeConfig
) -> "ee.Image":
    assert ee is not None
    w2, w1 = cfg.s2_fusion_weight, cfg.s1_fusion_weight
    w = w2 + w1
    n_b = max(2, int(math.floor(n * cfg.baseline_fraction)))
    if n_b >= n:
        n_b = n - 1
    n_rec = n - n_b
    if n_rec < 1 or n < cfg.min_months:
        return s2b.select(0).multiply(0).rename("z")
    b2n = s2b.bandNames().slice(0, n)
    b1n = s1b.bandNames().slice(0, n)
    s2a = s2b.select(b2n)
    s1a = s1b.select(b1n)
    z2 = _z_from_stack(s2a, n_b, n, "z2", ee)
    z1 = _z_from_stack(s1a, n_b, n, "z1", ee)
    return z2.multiply(w2).add(z1.multiply(w1)).divide(w).rename("z_fused")


def _z_s2_only(s2b: "ee.Image", n: int, cfg: AnalyzeConfig) -> "ee.Image":
    assert ee is not None
    n_b = max(2, int(math.floor(n * cfg.baseline_fraction)))
    if n_b >= n:
        n_b = n - 1
    b2n = s2b.bandNames().slice(0, n)
    s2a = s2b.select(b2n)
    if n < cfg.min_months or n - n_b < 1:
        return s2b.select(0).multiply(0).rename("z2")
    return _z_from_stack(s2a, n_b, n, "z2", ee)


def _geo_to_ee(geometry_geojson: dict) -> "ee.Geometry":
    return ee.Geometry(geometry_geojson)


def _s2_to_rgb3(image: "ee.Image") -> "ee.Image":
    """3-band S2 (B4, B3, B2) only, cloud-masked — homogeneous for median()."""
    qa = image.select("QA60")
    m = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
    img = image.updateMask(m).divide(10000.0)
    return img.select(["B4", "B3", "B2"])


def _s2_median_true_color(
    geom: "ee.Geometry", t_start: "ee.ComputedObject", t_end: "ee.ComputedObject"
) -> "ee.Image" | None:
    """Median RGB composite for [t_start, t_end)."""
    assert ee is not None
    c = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(geom)
        .filterDate(t_start, t_end)
    )
    try:
        m = c.map(_s2_to_rgb3).median()
        return m
    except Exception:  # noqa: BLE001
        return None


def _period_labels_iso(
    start_iso: str, n_months: int, n_b: int, n_r: int
) -> dict[str, Any]:
    t0 = parser.isoparse(start_iso)
    t0d = t0.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    t_b_end = t0d + relativedelta(months=n_b)  # start of “recent” (exclusive end of baseline)
    t_m_end = t0d + relativedelta(months=n_months)
    return {
        "baseline": {
            "start": t0d.date().isoformat(),
            "end": (t_b_end - relativedelta(days=1)).date().isoformat(),
            "n_months": n_b,
            "label": f"First {n_b} monthly composites from range start (mean/std for |Z|).",
        },
        "recent": {
            "start": t_b_end.date().isoformat(),
            "end": (t_m_end - relativedelta(days=1)).date().isoformat()
            if n_months
            else None,
            "n_months": n_r,
            "label": f"Last {n_r} months vs baseline — higher |MNDWI/SAR Z| = stronger departure.",
        },
    }


def _gee_explanation(
    geometry_geojson: dict,
    start: str,
    n_months: int,
    n_b: int,
    n_r: int,
    fused: bool,
    cfg: AnalyzeConfig,
) -> dict[str, Any]:
    assert ee is not None
    geom = _geo_to_ee(geometry_geojson)
    t0 = ee.Date(start)
    t_base_end = t0.advance(n_b, "month")
    t_rec_end = t0.advance(n_months, "month")
    out: dict[str, Any] = {
        "summary": (
            f"Scoring: per-pixel |Z| from S2 MNDWI monthly medians"
            f"{' fused with S1 VV dB' if fused else ''}. "
            f"Baseline = first {n_b} months; recent = {n_r} months. "
            f"Vector mask where |Z| >= {cfg.z_threshold} (screening, not a legal test)."
        ),
        "periods": _period_labels_iso(start, n_months, n_b, n_r),
    }
    if _geom_area_km2(geom) > 2500.0:
        out["thumbnails"] = {
            "error": "Preview skipped (use AOI under ~2500 km² for S2 getThumbURL).",
        }
        return out
    vis = {
        "bands": ["B4", "B3", "B2"],
        "min": 0.0,
        "max": 0.35,
        "dimensions": 480,
        "region": geom,
        "format": "png",
    }
    try:
        b_img = _s2_median_true_color(geom, t0, t_base_end)
        r_img = _s2_median_true_color(geom, t_base_end, t_rec_end)
        b_url: str | None
        r_url: str | None
        b_url = b_img.getThumbURL(vis) if b_img is not None else None
        r_url = r_img.getThumbURL(vis) if r_img is not None else None
        if not b_url and not r_url:
            out["thumbnails"] = {
                "error": "No cloud-free S2 in one or both windows; try a wider area or other dates."
            }
        else:
            out["thumbnails"] = {
                "caption_baseline": "S2 true-color median (cloud-masked) — baseline window",
                "caption_recent": "S2 true-color median (cloud-masked) — recent window",
                "baseline_s2_rgb_url": b_url,
                "recent_s2_rgb_url": r_url,
            }
    except Exception as ex:  # noqa: BLE001
        out["thumbnails"] = {"error": str(ex)}
    return out


def _mock_explanation() -> dict[str, Any]:
    return {
        "summary": "Mock: connect GEE for S2 before/after previews and full screening.",
        "periods": None,
        "thumbnails": {
            "disabled": "GEE not initialised; previews unavailable in mock mode.",
        },
    }


def _geom_area_km2(geom) -> float:
    return float(geom.area(maxError=1).getInfo()) / 1e6


def _analyze_gee(
    geometry_geojson: dict,
    start: str,
    end: str,
    cfg: AnalyzeConfig,
    include_s1: bool,
    include_explanation: bool = False,
) -> dict[str, Any]:
    assert ee is not None
    geom = _geo_to_ee(geometry_geojson)
    try:
        area = _geom_area_km2(geom)
    except Exception as ex:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"Geometry/area: {ex}",
            "features": {"type": "FeatureCollection", "features": []},
        }
    if area > cfg.max_area_km2:
        return {
            "ok": False,
            "error": f"Area {area:.1f} km² exceeds limit {cfg.max_area_km2} km².",
            "features": {"type": "FeatureCollection", "features": []},
        }

    n_m = _n_months_between(start, end)
    if n_m < cfg.min_months:
        return {
            "ok": False,
            "error": f"Date range has only {n_m} month(s); need at least {cfg.min_months}.",
            "features": {"type": "FeatureCollection", "features": []},
        }

    s2b = _monthly_s2_to_bands(geom, start, n_m)
    if s2b is None:
        return {
            "ok": False,
            "error": "Could not build S2 monthly stack.",
            "features": {"type": "FeatureCollection", "features": []},
        }
    n2 = len(s2b.bandNames().getInfo())
    if n2 < cfg.min_months:
        return {
            "ok": False,
            "error": f"Insufficient S2 months ({n2}).",
            "features": {"type": "FeatureCollection", "features": []},
        }

    fused = False
    s1b = None
    n1 = 0
    if include_s1:
        try:
            s1b = _monthly_s1_to_bands(geom, start, n2)
            n1 = len(s1b.bandNames().getInfo()) if s1b is not None else 0
        except Exception:  # noqa: BLE001
            s1b = None
            n1 = 0
    n = min(n2, n1) if n1 >= cfg.min_months and include_s1 and n1 > 0 else n2

    if s1b is not None and n1 >= cfg.min_months and include_s1 and n1 >= 4:
        s2b_u = s2b.select(s2b.bandNames().slice(0, n)) if n < n2 else s2b
        s1b_u = s1b.select(s1b.bandNames().slice(0, n)) if n < n1 else s1b
        z = _fused_z(s2b_u, s1b_u, n, cfg)
        fused = True
    else:
        z = _z_s2_only(s2b, n2, cfg)
        n = n2

    n_b = max(2, int(math.floor(n * cfg.baseline_fraction)))
    if n_b >= n:
        n_b = n - 1
    n_rec = n - n_b
    th = z.abs().gte(cfg.z_threshold).selfMask()
    try:
        vectors = th.reduceToVectors(
            geometry=geom,
            scale=cfg.s2_scale_m,
            maxPixels=1e7,
        )
        fc = vectors.getInfo()
        feats = fc.get("features", [])
    except Exception as ex:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"GEE vectorization: {ex}",
            "features": {"type": "FeatureCollection", "features": []},
        }

    metric = "z_score_fused_mndwi_sar" if fused else "z_score_mndwi"
    for f in feats:
        f.setdefault("properties", {})
        f["properties"].update(
            {
                "layer": "suspicious_morphology_change",
                "metric": metric,
                "disclaimer": "Screening only; not proof of legality/illegality.",
            }
        )

    out: dict[str, Any] = {
        "ok": True,
        "gee": True,
        "metadata": {
            "area_km2": round(area, 2),
            "months": n,
            "baseline_months": n_b,
            "recent_months": n_rec,
            "z_threshold": cfg.z_threshold,
            "fused_s1_s2": fused,
        },
        "features": {"type": "FeatureCollection", "features": feats},
    }
    if include_explanation:
        try:
            out["explanation"] = _gee_explanation(
                geometry_geojson, start, n, n_b, n_rec, fused, cfg
            )
        except Exception as ex:  # noqa: BLE001
            out["explanation"] = {
                "summary": "Could not build Phase B explanation (thumbnails/periods).",
                "error": str(ex),
            }
    return out


def _mock_analyze(
    geometry_geojson: dict, start: str, end: str, include_explanation: bool
) -> dict[str, Any]:
    g = None
    if shape is not None and box is not None and Point is not None and mapping is not None:  # noqa: E501
        try:
            g = shape(geometry_geojson)
        except Exception:
            g = None
    if g is None and box is not None:
        g = box(-0.1, 51.4, -0.05, 51.5)
    assert g is not None
    c = g.centroid
    ox, oy = float(c.x), float(c.y)
    rng = np.random.default_rng(42)
    feats: list[dict] = []
    for i in range(3):
        d = rng.normal(0, 0.002, 2)
        jx, jy = float(ox) + float(d[0]), float(oy) + float(d[1])
        p = Point(float(jx), float(jy)).buffer(0.0012 + 0.0003 * i)
        inter = g.intersection(p)
        if not inter.is_empty and mapping is not None:
            feats.append(
                {
                    "type": "Feature",
                    "geometry": mapping(inter),
                    "properties": {
                        "layer": "suspicious_morphology_change",
                        "metric": "z_score_mndwi",
                        "mock": True,
                        "note": "Set GEE credentials; unset GEE_MOCK for real analysis",
                    },
                }
            )
    if not feats and mapping is not None:
        feats.append(
            {
                "type": "Feature",
                "geometry": mapping(g),
                "properties": {
                    "layer": "suspicious_morphology_change",
                    "metric": "z_score_mndwi",
                    "mock": True,
                },
            }
        )
    m: dict[str, Any] = {
        "ok": True,
        "gee": False,
        "metadata": {
            "baseline_note": f"{start}..{end} (mock)",
        },
        "features": {"type": "FeatureCollection", "features": feats},
    }
    if include_explanation:
        m["explanation"] = _mock_explanation()
    return m


def analyze_aoi(
    geometry_geojson: dict,
    start_date: str,
    end_date: str,
    cfg: Optional[AnalyzeConfig] = None,
    include_s1: bool = True,
    include_explanation: bool = True,
) -> dict[str, Any]:
    cfg = cfg or AnalyzeConfig()
    if gee_is_ready() and ee is not None:
        return _analyze_gee(
            geometry_geojson,
            start_date,
            end_date,
            cfg,
            include_s1,
            include_explanation=include_explanation,
        )
    return _mock_analyze(geometry_geojson, start_date, end_date, include_explanation)
