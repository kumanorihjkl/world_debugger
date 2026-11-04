import { useCallback, useEffect, useRef, useState } from "react";
import { analyzeFrame, compileRule, deleteRule, health, listRules } from "./api/client";
import type {
  SceneObject,
  Status,
  Violation,
  VisualRule,
  Zone,
} from "./types";

const POLL_MS = 2000;

function drawOverlay(
  canvas: HTMLCanvasElement,
  video: HTMLVideoElement | null,
  objects: SceneObject[],
  violatingIds: Set<string>,
  zones: Zone[],
  draft: { x0: number; y0: number; x1: number; y1: number } | null,
): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = (canvas.width = canvas.clientWidth || 640);
  const h = (canvas.height = canvas.clientHeight || 480);
  const live = !!video && video.readyState >= 2 && video.videoWidth > 0;
  if (!live) {
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = "#9aa6b2";
    ctx.font = "14px sans-serif";
    ctx.fillText("Camera off — press Start camera", 16, 30);
    return;
  }
  for (const z of zones) {
    ctx.strokeStyle = "#f5a524";
    ctx.setLineDash([6, 4]);
    ctx.lineWidth = 2;
    ctx.beginPath();
    z.polygon.forEach(([px, py], i) => {
      const X = px * w;
      const Y = py * h;
      if (i === 0) ctx.moveTo(X, Y);
      else ctx.lineTo(X, Y);
    });
    ctx.closePath();
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#f5a524";
    ctx.font = "12px monospace";
    ctx.fillText(z.name, z.polygon[0][0] * w + 4, z.polygon[0][1] * h - 6);
  }
  if (draft) {
    ctx.strokeStyle = "#f5a524";
    ctx.lineWidth = 2;
    ctx.strokeRect(
      draft.x0 * w,
      draft.y0 * h,
      (draft.x1 - draft.x0) * w,
      (draft.y1 - draft.y0) * h,
    );
  }
  for (const o of objects) {
    const bad = violatingIds.has(o.id);
    const x = o.bbox.x_min * w;
    const y = o.bbox.y_min * h;
    const contour = o.polygon && o.polygon.length >= 3 ? o.polygon : null;
    ctx.strokeStyle = bad ? "#e5484d" : "#35c26e";
    if (contour) {
      ctx.beginPath();
      contour.forEach(([px, py], i) => {
        const X = px * w;
        const Y = py * h;
        if (i === 0) ctx.moveTo(X, Y);
        else ctx.lineTo(X, Y);
      });
      ctx.closePath();
      if (bad) {
        ctx.fillStyle = "rgba(229,72,77,0.25)";
        ctx.fill();
      }
      ctx.lineWidth = bad ? 2.5 : 2;
      ctx.stroke();
    } else {
      // Fallback when no contour is available (mock mode, decode failure).
      if (bad) {
        ctx.fillStyle = "rgba(229,72,77,0.25)";
        ctx.fillRect(x, y, (o.bbox.x_max - o.bbox.x_min) * w, (o.bbox.y_max - o.bbox.y_min) * h);
      }
      ctx.lineWidth = bad ? 3 : 1.5;
      ctx.strokeRect(x, y, (o.bbox.x_max - o.bbox.x_min) * w, (o.bbox.y_max - o.bbox.y_min) * h);
    }
    ctx.fillStyle = bad ? "#e5484d" : "#35c26e";
    ctx.font = "12px monospace";
    ctx.fillText(`${o.concept} ${Math.round(o.confidence * 100)}%`, x + 4, y - 4 > 10 ? y - 4 : y + 14);
  }
}

export default function App(): JSX.Element {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const snapRef = useRef<HTMLCanvasElement>(null);

  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState("");
  const [ruleText, setRuleText] = useState("Keep drinks away from laptops.");
  const [creating, setCreating] = useState(false);
  const [rules, setRules] = useState<VisualRule[]>([]);
  const [compiledNote, setCompiledNote] = useState("");
  const [mocked, setMocked] = useState<boolean | null>(null);
  const [objects, setObjects] = useState<SceneObject[]>([]);
  const [violations, setViolations] = useState<Violation[]>([]);
  const [resolvedFlash, setResolvedFlash] = useState(false);
  const [zones, setZones] = useState<Zone[]>([]);
  const [zoneName, setZoneName] = useState("doorway");
  const [drawing, setDrawing] = useState(false);
  const [draft, setDraft] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [auto, setAuto] = useState(false);
  const [autoNote, setAutoNote] = useState("");

const AUTO_STOP_MS = 3 * 60 * 1000;

  const prevViolationCount = useRef(0);
  const analyzingRef = useRef(false);
  const stateRef = useRef({ rules, zones });
  stateRef.current = { rules, zones };

  useEffect(() => {
    health()
      .then((h) => setMocked(h.mock_meta_api))
      .catch(() => setMocked(null));
    listRules()
      .then((r) => setRules(r.rules))
      .catch(() => {
        /* offline backend: keep empty list, error surfaces on action */
      });
  }, []);

  const startCamera = useCallback(async () => {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      const v = videoRef.current;
      if (v) {
        v.srcObject = stream;
        await v.play();
      }
      setStatus((s) => (s === "idle" ? "capturing" : s));
    } catch (e) {
      setError(`Camera failed: ${e instanceof Error ? e.message : String(e)}`);
      setStatus("error");
    }
  }, []);

  const snapshotBase64 = useCallback((): string => {
    const v = videoRef.current;
    const c = snapRef.current;
    if (!v || !c || v.readyState < 2) return "";
    c.width = v.videoWidth || 640;
    c.height = v.videoHeight || 480;
    const ctx = c.getContext("2d");
    if (!ctx) return "";
    ctx.drawImage(v, 0, 0, c.width, c.height);
    const url = c.toDataURL("image/jpeg", 0.8);
    return url.includes(",") ? url.split(",")[1] : "";
  }, []);

  const runAnalyze = useCallback(
    async (imageVariant = "default") => {
      if (analyzingRef.current) return;
      analyzingRef.current = true;
      setStatus("analyzing");
      setError("");
      try {
        const { zones: z } = stateRef.current;
        const imageBase64 = imageVariant === "default" ? snapshotBase64() : "";
        const res = await analyzeFrame({ imageBase64, imageVariant, zones: z });
        setMocked(res.mocked);
        setObjects(res.scene.objects);
        const viol = res.violations;
        if (prevViolationCount.current > 0 && viol.length === 0) {
          setResolvedFlash(true);
          window.setTimeout(() => setResolvedFlash(false), 4000);
        }
        prevViolationCount.current = viol.length;
        setViolations(viol);
        setStatus(viol.length > 0 ? "violation" : "safe");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setStatus("error");
      } finally {
        analyzingRef.current = false;
      }
    },
    [snapshotBase64],
  );

  useEffect(() => {
    if (!auto) return;
    setAutoNote("");
    const t = window.setInterval(() => void runAnalyze(), POLL_MS);
    // Cost guard: stop auto analysis after 3 minutes.
    const stop = window.setTimeout(() => {
      setAuto(false);
      setAutoNote("Auto stopped after 3 min to save API cost.");
    }, AUTO_STOP_MS);
    return () => {
      window.clearInterval(t);
      window.clearTimeout(stop);
    };
  }, [auto, runAnalyze]);

  useEffect(() => {
    const v = videoRef.current;
    const c = canvasRef.current;
    if (!v || !c) return;
    const viol = new Set<string>();
    violations.forEach((x) => x.object_ids.forEach((id) => viol.add(id)));
    const draw = (): void => {
      drawOverlay(c, v, objects, viol, zones, draft);
    };
    draw();
    const t = window.setInterval(draw, 500);
    return () => window.clearInterval(t);
  }, [objects, violations, zones, draft]);

  const createRule = useCallback(async () => {
    if (creating) return;
    setCreating(true);
    setError("");
    setCompiledNote("");
    try {
      const res = await compileRule(ruleText);
      setRules((prev) => [...prev.filter((r) => r.id !== res.rule.id), res.rule]);
      setMocked(res.mocked);
      setCompiledNote("✓ Visual rule compiled");
      setStatus((s) => (s === "idle" ? "capturing" : s));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }, [ruleText, creating]);

  const removeRule = useCallback(async (id: string) => {
    try {
      await deleteRule(id);
    } catch {
      /* backend is in-memory; still drop locally */
    }
    setRules((prev) => prev.filter((r) => r.id !== id));
  }, []);

  const canvasPos = (e: React.MouseEvent): { x: number; y: number } => {
    const c = canvasRef.current;
    if (!c) return { x: 0, y: 0 };
    const r = c.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    };
  };

  return (
    <>
      <header className="topbar">
        <h1>WorldDebugger</h1>
        <span className="tagline">Debug the physical world.</span>
        <span className="spacer" />
        <span className={`status-pill ${status}`}>{status}</span>
      </header>
      <main className="layout">
        <section className="card">
          <h2>Live Camera</h2>
          <div className="camera-wrap">
            <video ref={videoRef} muted playsInline autoPlay />
            <canvas
              ref={canvasRef}
              className="overlay"
              onMouseDown={(e) => {
                if (!drawing) return;
                const p = canvasPos(e);
                setDraft({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
              }}
              onMouseMove={(e) => {
                if (!drawing || !draft) return;
                const p = canvasPos(e);
                setDraft({ ...draft, x1: p.x, y1: p.y });
              }}
              onMouseUp={() => {
                if (!drawing || !draft) return;
                const name = zoneName.trim() || "zone";
                const poly: [number, number][] = [
                  [Math.min(draft.x0, draft.x1), Math.min(draft.y0, draft.y1)],
                  [Math.max(draft.x0, draft.x1), Math.min(draft.y0, draft.y1)],
                  [Math.max(draft.x0, draft.x1), Math.max(draft.y0, draft.y1)],
                  [Math.min(draft.x0, draft.x1), Math.max(draft.y0, draft.y1)],
                ];
                setZones((prev) => [...prev.filter((z) => z.id !== name), { id: name, name, polygon: poly }]);
                setDraft(null);
                setDrawing(false);
              }}
            />
          </div>
          <canvas ref={snapRef} style={{ display: "none" }} />
          <div className="row">
            <button onClick={() => void startCamera()}>Start camera</button>
            <button onClick={() => void runAnalyze()}>Analyze</button>
            <button className={auto ? "on" : ""} onClick={() => setAuto((a) => !a)}>
              Auto {auto ? "on" : "off"}
            </button>
            {autoNote && !auto && <span className="hint">{autoNote}</span>}
            <button
              className={drawing ? "on" : ""}
              onClick={() => {
                setDrawing((d) => !d);
                setDraft(null);
              }}
            >
              {drawing ? "Drawing zone… click-drag" : "Draw zone"}
            </button>
            <input
              type="text"
              value={zoneName}
              onChange={(e) => setZoneName(e.target.value)}
              placeholder="zone name"
              style={{ maxWidth: 140, flex: "none" }}
            />
          </div>
          <div className="row">
            {zones.map((z) => (
              <span key={z.id} className="zone-chip">
                {z.name}
                <button onClick={() => setZones((prev) => prev.filter((x) => x.id !== z.id))}>×</button>
              </span>
            ))}
          </div>
          {error && <div className="error">{error}</div>}
          <p className="hint">
            Realtime preview, snapshot analysis every {POLL_MS / 1000}s when Auto is on
            (Auto stops after 3 min).
            Drag on the overlay to draw a zone rectangle.
          </p>
        </section>

        <div>
          <section className="card">
            <h2>Rules</h2>
            <div className="row" style={{ marginTop: 0 }}>
              <input
                type="text"
                value={ruleText}
                onChange={(e) => setRuleText(e.target.value)}
                placeholder="Describe a rule for this space..."
                onKeyDown={(e) => {
                  if (e.key === "Enter") void createRule();
                }}
              />
              <button
                className="primary"
                onClick={() => void createRule()}
                disabled={creating || ruleText.trim().length === 0}
              >
                {creating ? "Creating…" : "Create Rule"}
              </button>
            </div>
            {compiledNote && <div className="ok-line">{compiledNote}</div>}
            {rules.map((r) => (
              <div key={r.id} className="rule-item">
                <div className="head">
                  <strong>{r.name}</strong>
                  <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                    <span className={`sev ${r.severity}`}>{r.severity}</span>
                    <button onClick={() => void removeRule(r.id)}>Delete</button>
                  </span>
                </div>
                <div className="meta">
                  {r.condition.operator} · {r.original_text}
                </div>
                <div className="meta">
                  detects: {r.selectors.map((s) => s.sam_prompt).join(", ")}
                </div>
                {r.condition.requires_metric_depth && (
                  <div className="error">Needs metric depth — not available in this MVP.</div>
                )}
              </div>
            ))}
            {rules.length === 0 && <p className="hint">No rules yet. Try “Keep drinks away from laptops.”</p>}
          </section>

          <section className="card" style={{ marginTop: 16 }}>
            <h2>Issues</h2>
            {violations.map((v, i) => (
              <div key={`${v.rule_id}-${i}`} className="issue">
                <div className="title">
                  ⚠ {v.rule_name}
                </div>
                <div>{v.message}</div>
                <div className="time">Detected just now</div>
              </div>
            ))}
            {violations.length === 0 && <div className="ok-line">✓ No violations</div>}
            {resolvedFlash && <div className="resolved-toast">✓ Resolved</div>}
            <h2 style={{ marginTop: 12 }}>Detected objects</h2>
            {objects.length === 0 && <p className="hint">Nothing detected in the last frame.</p>}
            {objects.map((o) => (
              <div key={o.id} className="meta" style={{ fontFamily: "monospace", fontSize: 11 }}>
                {o.concept} {Math.round(o.confidence * 100)}% [{o.bbox.x_min.toFixed(2)},{" "}
                {o.bbox.y_min.toFixed(2)}, {o.bbox.x_max.toFixed(2)}, {o.bbox.y_max.toFixed(2)}]
              </div>
            ))}
          </section>

          <section className="card" style={{ marginTop: 16 }}>
            <h2>Demo without camera</h2>
            <div className="row" style={{ marginTop: 0 }}>
              <button onClick={() => void runAnalyze("default")}>Simulate: drink near laptop</button>
              <button onClick={() => void runAnalyze("far")}>Simulate: drink moved away</button>
            </div>
            <p className="hint">Fixture frames for the Demo 1 violation → Resolved flow.</p>
          </section>
        </div>
      </main>
      <footer className="foot">
        Powered by Muse Spark 1.3 + SAM 3.1{mocked ? " · Mock mode" : ""}
      </footer>
    </>
  );
}
