import { useCallback, useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import type { MapMouseEvent, Map, StyleSpecification } from "maplibre-gl";
import type { FeatureCollection, Polygon } from "geojson";
import "./App.css";

type Fc = FeatureCollection;
type GjGeometry = Polygon;

const defaultPoly: GjGeometry = {
  type: "Polygon",
  coordinates: [
    [
      [105.75, 9.6],
      [105.9, 9.6],
      [105.9, 9.5],
      [105.75, 9.5],
      [105.75, 9.6],
    ],
  ],
};

const emptyFc: Fc = { type: "FeatureCollection", features: [] };

/** Esri World Imagery (no API key; subject to Esri / ArcGIS terms of use). */
const SATELLITE_STYLE: StyleSpecification = {
  version: 8,
  name: "Esri World Imagery",
  sources: {
    esri: {
      type: "raster",
      tileSize: 256,
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      attribution:
        "Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    },
  },
  layers: [
    {
      id: "esri",
      type: "raster",
      source: "esri",
      minzoom: 0,
      maxzoom: 22,
    },
  ],
};

type Health = { gee: boolean; gee_message: string };
type PeriodBlock = {
  start?: string;
  end?: string;
  n_months?: number;
  label?: string;
};
type PhaseBExplanation = {
  summary?: string;
  error?: string;
  periods?: { baseline?: PeriodBlock; recent?: PeriodBlock } | null;
  thumbnails?: {
    error?: string;
    disabled?: string;
    caption_baseline?: string;
    caption_recent?: string;
    baseline_s2_rgb_url?: string | null;
    recent_s2_rgb_url?: string | null;
  };
};
type Analysis = {
  ok: boolean;
  gee?: boolean;
  error?: string;
  metadata?: Record<string, unknown>;
  features: Fc;
  explanation?: PhaseBExplanation;
};

export function App() {
  const el = useRef<HTMLDivElement>(null);
  const map = useRef<Map | null>(null);
  const [start, setStart] = useState("2018-01-01");
  const [end, setEnd] = useState("2023-12-01");
  const [z, setZ] = useState(2);
  const [includeS1, setIncludeS1] = useState(true);
  const [aoi, setAoi] = useState<GeoJSON.Polygon>(defaultPoly);
  const [drawMode, setDrawMode] = useState(false);
  const drawRing = useRef<number[][]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(false);
  const [res, setRes] = useState<Analysis | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [includePreviews, setIncludePreviews] = useState(true);

  const startDraw = useCallback(() => {
    drawRing.current = [];
    const m = map.current;
    if (m?.getLayer("line-preview-ln")) {
      m.removeLayer("line-preview-ln");
    }
    if (m?.getSource("line-preview")) {
      m.removeSource("line-preview");
    }
    setDrawMode(true);
  }, []);

  const cancelDraw = useCallback(() => {
    setDrawMode(false);
    drawRing.current = [];
  }, []);

  useEffect(() => {
    if (!el.current) {
      return;
    }
    if (map.current) {
      return;
    }
    const m = new maplibregl.Map({
      container: el.current,
      style: SATELLITE_STYLE,
      center: [105.82, 9.55],
      zoom: 9,
    });
    map.current = m;
    m.addControl(new maplibregl.NavigationControl());
    m.addControl(
      new maplibregl.AttributionControl({ compact: true }),
    );
    m.on("load", () => {
      m.addSource("aoi", {
        type: "geojson",
        data: { type: "Feature", properties: {}, geometry: defaultPoly } as const,
      });
      m.addLayer({ id: "aoi-fill", type: "fill", source: "aoi", paint: { "fill-color": "#1f6feb", "fill-opacity": 0.2 } });
      m.addLayer({ id: "aoi-stroke", type: "line", source: "aoi", paint: { "line-color": "#1f6feb", "line-width": 2 } });
      m.addSource("anomaly", { type: "geojson", data: emptyFc });
      m.addLayer({ id: "anomaly-fill", type: "fill", source: "anomaly", paint: { "fill-color": "#a40e26", "fill-opacity": 0.55 } });
      m.addLayer({ id: "anomaly-line", type: "line", source: "anomaly", paint: { "line-color": "#ff7b72", "line-width": 1 } });
    });
    return () => {
      m.remove();
      map.current = null;
    };
  }, []);

  const updateAoiSource = useCallback((g: GjGeometry) => {
    const s = map.current?.getSource("aoi");
    if (s && s.type === "geojson") {
      s.setData({ type: "Feature", properties: {}, geometry: g } as const);
    }
  }, []);

  const updateAnomaly = useCallback((g: Fc) => {
    const s = map.current?.getSource("anomaly");
    if (s && s.type === "geojson") {
      s.setData(g);
    }
  }, []);

  useEffect(() => {
    updateAoiSource(aoi);
  }, [aoi, updateAoiSource]);

  const onMapClick = useCallback(
    (e: MapMouseEvent) => {
      if (!drawMode) {
        return;
      }
      const c = e.lngLat.toArray() as [number, number];
      const ring = drawRing.current;
      ring.push(c);
      if (ring.length < 2) {
        return;
      }
      const m = map.current;
      if (!m) {
        return;
      }
      if (!m.getSource("line-preview")) {
        m.addSource("line-preview", {
          type: "geojson",
          data: {
            type: "Feature",
            properties: {},
            geometry: { type: "LineString", coordinates: ring },
          },
        });
        m.addLayer({
          id: "line-preview-ln",
          type: "line",
          source: "line-preview",
          paint: { "line-color": "#58a6ff", "line-width": 2, "line-dasharray": [2, 1] },
        });
      } else {
        const s = m.getSource("line-preview");
        if (s && s.type === "geojson") {
          s.setData({
            type: "Feature",
            properties: {},
            geometry: { type: "LineString", coordinates: ring },
          } as const);
        }
      }
    },
    [drawMode],
  );

  const commitDraw = useCallback(() => {
    const r = drawRing.current;
    if (r.length < 3) {
      setErr("Draw at least 3 points, then click Finish polygon.");
      return;
    }
    const first = r[0]!;
    const last = r[r.length - 1]!;
    if (last[0] !== first[0] || last[1] !== first[1]) {
      r.push([first[0]!, first[1]!]);
    }
    setDrawMode(false);
    const poly: GjGeometry = { type: "Polygon", coordinates: [r] };
    setAoi(poly);
    const m = map.current;
    if (m?.getLayer("line-preview-ln")) {
      m.removeLayer("line-preview-ln");
    }
    if (m?.getSource("line-preview")) {
      m.removeSource("line-preview");
    }
  }, [setErr]);

  useEffect(() => {
    if (!drawMode) {
      return;
    }
    const m = map.current;
    if (!m) {
      return;
    }
    m.getCanvas().style.cursor = "crosshair";
    m.on("click", onMapClick);
    return () => {
      m.getCanvas().style.cursor = "";
      m.off("click", onMapClick);
    };
  }, [drawMode, onMapClick]);

  useEffect(() => {
    fetch("/api/health")
      .then((x) => x.json())
      .then((j: Health) => setHealth(j))
      .catch(() => setHealth({ gee: false, gee_message: "API unreachable (start backend?)" }));
  }, []);

  const run = async () => {
    setErr(null);
    setLoading(true);
    setRes(null);
    try {
      const r = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          geometry: aoi,
          start_date: `${start}T00:00:00Z`,
          end_date: `${end}T00:00:00Z`,
          include_s1: includeS1,
          z_threshold: z,
          include_explanation: includePreviews,
        }),
      });
      const j = (await r.json()) as Analysis;
      setRes(j);
      if (j.ok) {
        updateAnomaly(j.features);
      } else {
        setErr(j.error || "Request failed");
        updateAnomaly(emptyFc);
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="app">
      <div className="toolbar">
        <div>
          <h1>River change screening (Sentinel-1/2, GEE)</h1>
          <p className="hint">Highlights <strong>unusual</strong> recent MNDWI/SAR z-scores in your AOI, not a finding of “illegal” mining. Validate with local permits and field work.</p>
        </div>
        <div className="field-group">
          <div className="field">
            <label>Start (UTC)</label>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </div>
          <div className="field">
            <label>End</label>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </div>
          <div className="field">
            <label>|Z| &ge;</label>
            <input
              type="number"
              step="0.5"
              min="0.5"
              value={z}
              onChange={(e) => setZ(Number(e.target.value))}
            />
          </div>
          <div className="field" style={{ alignItems: "flex-start" }}>
            <label>
              <input
                type="checkbox"
                checked={includeS1}
                onChange={(e) => setIncludeS1(e.target.checked)}
              />
              Fuse Sentinel-1 (VV) with S2
            </label>
          </div>
          <div className="field" style={{ alignItems: "flex-start" }}>
            <label>
              <input
                type="checkbox"
                checked={includePreviews}
                onChange={(e) => setIncludePreviews(e.target.checked)}
              />
              Phase B: S2 before/after previews (slower)
            </label>
          </div>
        </div>
        <div>
          <button className="secondary" type="button" onClick={startDraw} disabled={drawMode}>
            Draw new AOI
          </button>{" "}
          <button type="button" onClick={commitDraw} disabled={!drawMode}>
            Finish polygon
          </button>{" "}
          <button className="secondary" type="button" onClick={cancelDraw} disabled={!drawMode}>
            Cancel draw
          </button>{" "}
          <button type="button" onClick={run} disabled={loading}>
            {loading ? "Running…" : "Run screening"}
          </button>
        </div>
        {health && <div className="field"><span>API: {health.gee ? "GEE" : "mock/offline"} — {health.gee_message}</span></div>}
        {res?.metadata && (
          <div className="result-meta" title={JSON.stringify(res.metadata, null, 0)}>
            Area {String(res.metadata.area_km2 ?? "—")} km² · {String(res.metadata.months ?? "—")} months
            (baseline {String(res.metadata.baseline_months ?? "—")} / recent {String(res.metadata.recent_months ?? "—")})
            · |Z| &ge; {String(res.metadata.z_threshold)} ·
            S1+S2 {res.metadata.fused_s1_s2 ? "on" : "S2 only"}
          </div>
        )}
      </div>
      {err && <div className="error toolbar">{err}</div>}
      <div className="map-and-side">
        <div className="maprow">
          {drawMode && <div className="drawing-help">Clicks: add vertex. Then “Finish polygon” (or cancel).</div>}
          <div id="map" ref={el} />
        </div>
        {res?.ok && res.explanation && (
          <aside className="explain-aside">
            <h2>What this run means (Phase B)</h2>
            {res.explanation.summary && <p className="explain-text">{res.explanation.summary}</p>}
            {res.explanation.error && <p className="error">Explanation: {res.explanation.error}</p>}
            {res.explanation.periods?.baseline && (
              <div className="period-block">
                <strong>Baseline period</strong>
                <p>
                  {res.explanation.periods.baseline.start} → {res.explanation.periods.baseline.end}
                </p>
                <p className="sub">{res.explanation.periods.baseline.label}</p>
              </div>
            )}
            {res.explanation.periods?.recent && (
              <div className="period-block">
                <strong>Recent period (vs baseline)</strong>
                <p>
                  {res.explanation.periods.recent.start} → {res.explanation.periods.recent.end}
                </p>
                <p className="sub">{res.explanation.periods.recent.label}</p>
              </div>
            )}
            {res.explanation.thumbnails && (
              <div className="thumbs">
                {res.explanation.thumbnails.error && <p className="error">{res.explanation.thumbnails.error}</p>}
                {res.explanation.thumbnails.disabled && <p className="hint">{res.explanation.thumbnails.disabled}</p>}
                {res.explanation.thumbnails.baseline_s2_rgb_url && (
                  <figure>
                    <figcaption>{res.explanation.thumbnails.caption_baseline}</figcaption>
                    <img
                      src={res.explanation.thumbnails.baseline_s2_rgb_url}
                      alt="Baseline S2"
                      className="thumb"
                    />
                  </figure>
                )}
                {res.explanation.thumbnails.recent_s2_rgb_url && (
                  <figure>
                    <figcaption>{res.explanation.thumbnails.caption_recent}</figcaption>
                    <img
                      src={res.explanation.thumbnails.recent_s2_rgb_url}
                      alt="Recent S2"
                      className="thumb"
                    />
                  </figure>
                )}
              </div>
            )}
          </aside>
        )}
      </div>
      <div className="legend">Red fill: |Z| ≥ your threshold. Baseline ≈ first 65% of months in the range; the rest = “recent.” Thumbnails: cloud-masked S2 true-color <em>medians</em> over each window (not a single date).</div>
    </div>
  );
}
