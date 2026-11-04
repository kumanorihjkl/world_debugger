import { useCallback, useEffect, useRef, useState } from "react";
import { analyzeFrame, compileRule, deleteRule, health, listRules } from "./api/client";
import type {
  BoundingBox,
  SceneObject,
  Status,
  Violation,
  VisualRule,
  Zone,
} from "./types";

const POLL_MS = 2000;
const AUTO_STOP_MS = 3 * 60 * 1000;
const ROTATIONS = [0, 90, 180, 270] as const;

interface ContentRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

// Miniature canvases for ambient-mode background. Downsample plus a small
// hand-rolled gaussian blur reads as a soft blur when stretched, identically
// in every browser (ctx.filter is unsupported in some embedded browsers).
const AMBIENT_SIZE = 96;
const AMBIENT_TINY = 24;
const AMBIENT_BLUR_RADIUS = 5;
const AMBIENT_BLUR_PASSES = 3;
let ambientCanvas: HTMLCanvasElement | null = null;
let ambientTiny: HTMLCanvasElement | null = null;

function blurCanvas(canvas: HTMLCanvasElement, radius: number, passes: number): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = canvas.width;
  const h = canvas.height;
  if (w === 0 || h === 0 || radius <= 0) return;
  let src = ctx.getImageData(0, 0, w, h);
  const tmp = ctx.createImageData(w, h);
  const div = radius * 2 + 1;
  for (let p = 0; p < passes; p += 1) {
    // Horizontal sliding-window box blur.
    const s = src.data;
    const t = tmp.data;
    for (let y = 0; y < h; y += 1) {
      let r = 0;
      let g = 0;
      let b = 0;
      let a = 0;
      const row = y * w * 4;
      for (let x = -radius; x <= radius; x += 1) {
        const cx = Math.min(w - 1, Math.max(0, x)) * 4 + row;
        r += s[cx];
        g += s[cx + 1];
        b += s[cx + 2];
        a += s[cx + 3];
      }
      for (let x = 0; x < w; x += 1) {
        const o = row + x * 4;
        t[o] = r / div;
        t[o + 1] = g / div;
        t[o + 2] = b / div;
        t[o + 3] = a / div;
        const sub = Math.min(w - 1, Math.max(0, x - radius)) * 4 + row;
        const add = Math.min(w - 1, Math.max(0, x + radius + 1)) * 4 + row;
        r += s[add] - s[sub];
        g += s[add + 1] - s[sub + 1];
        b += s[add + 2] - s[sub + 2];
        a += s[add + 3] - s[sub + 3];
      }
    }
    // Vertical pass (reads tmp, writes back into src).
    const s2 = tmp.data;
    const t2 = src.data;
    for (let x = 0; x < w; x += 1) {
      let r = 0;
      let g = 0;
      let b = 0;
      let a = 0;
      for (let y = -radius; y <= radius; y += 1) {
        const cy = (Math.min(h - 1, Math.max(0, y)) * w + x) * 4;
        r += s2[cy];
        g += s2[cy + 1];
        b += s2[cy + 2];
        a += s2[cy + 3];
      }
      for (let y = 0; y < h; y += 1) {
        const o = (y * w + x) * 4;
        t2[o] = r / div;
        t2[o + 1] = g / div;
        t2[o + 2] = b / div;
        t2[o + 3] = a / div;
        const sub = (Math.min(h - 1, Math.max(0, y - radius)) * w + x) * 4;
        const add = (Math.min(h - 1, Math.max(0, y + radius + 1)) * w + x) * 4;
        r += s2[add] - s2[sub];
        g += s2[add + 1] - s2[sub + 1];
        b += s2[add + 2] - s2[sub + 2];
        a += s2[add + 3] - s2[sub + 3];
      }
    }
  }
  ctx.putImageData(src, 0, 0);
}

function drawAmbientBackground(
  ctx: CanvasRenderingContext2D,
  v: HTMLVideoElement,
  W: number,
  H: number,
  rot: number,
): void {
  if (typeof document === "undefined") return;
  if (!ambientCanvas) {
    ambientCanvas = document.createElement("canvas");
    ambientCanvas.width = AMBIENT_SIZE;
    ambientCanvas.height = AMBIENT_SIZE;
    // Pixel readbacks for the hand-rolled blur.
    ambientCanvas.getContext("2d", { willReadFrequently: true });
  }
  const actx = ambientCanvas.getContext("2d");
  if (!actx) return;
  const sw = v.videoWidth;
  const sh = v.videoHeight;
  const S = AMBIENT_SIZE;
  const scale = Math.max(S / sw, S / sh);
  actx.save();
  actx.clearRect(0, 0, S, S);
  if (rot === 90) {
    actx.translate(S, 0);
    actx.rotate(Math.PI / 2);
  } else if (rot === 270) {
    actx.translate(0, S);
    actx.rotate(-Math.PI / 2);
  }
  actx.drawImage(v, (S - sw * scale) / 2, (S - sh * scale) / 2, sw * scale, sh * scale);
  actx.restore();
  blurCanvas(ambientCanvas, AMBIENT_BLUR_RADIUS, AMBIENT_BLUR_PASSES);
  if (!ambientTiny) {
    ambientTiny = document.createElement("canvas");
    ambientTiny.width = AMBIENT_TINY;
    ambientTiny.height = AMBIENT_TINY;
  }
  const tinyCtx = ambientTiny.getContext("2d");
  if (!tinyCtx) return;
  tinyCtx.save();
  tinyCtx.imageSmoothingEnabled = true;
  tinyCtx.imageSmoothingQuality = "high";
  tinyCtx.clearRect(0, 0, AMBIENT_TINY, AMBIENT_TINY);
  tinyCtx.drawImage(ambientCanvas, 0, 0, AMBIENT_TINY, AMBIENT_TINY);
  tinyCtx.restore();
  ctx.save();
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  // Overdraw edges so the upscale has no transparent rim.
  ctx.drawImage(ambientTiny, -8, -8, W + 16, H + 16);
  ctx.restore();
}

function drawVideoFrame(
  ctx: CanvasRenderingContext2D,
  v: HTMLVideoElement,
  W: number,
  H: number,
  rot: number,
): ContentRect {
  const full: ContentRect = { x: 0, y: 0, w: W, h: H };
  const sw = v.videoWidth;
  const sh = v.videoHeight;
  if (sw === 0 || sh === 0) return full;
  const rotated = rot % 180 !== 0;
  if (rotated) {
    // Ambient mode: blurred fill instead of black bars.
    drawAmbientBackground(ctx, v, W, H, rot);
  }
  // Target size in rotated space. Upright fills the stage (cover); rotated
  // fits the whole frame (contain) so nothing is cropped away.
  const tw = rot % 180 !== 0 ? H : W;
  const th = rot % 180 !== 0 ? W : H;
  const scale =
    rot % 180 !== 0
      ? Math.min(tw / sw, th / sh)
      : Math.max(tw / sw, th / sh);
  const dw = sw * scale;
  const dh = sh * scale;
  const dx = (tw - dw) / 2;
  const dy = (th - dh) / 2;
  ctx.save();
  if (rot === 90) {
    ctx.translate(W, 0);
    ctx.rotate(Math.PI / 2);
  } else if (rot === 180) {
    ctx.translate(W, H);
    ctx.rotate(Math.PI);
  } else if (rot === 270) {
    ctx.translate(0, H);
    ctx.rotate(-Math.PI / 2);
  }
  ctx.drawImage(v, dx, dy, dw, dh);
  ctx.restore();
  // Content rect in canvas pixels (for mapping normalized overlay coords).
  if (rot === 90) return { x: W - dy - dh, y: dx, w: dh, h: dw };
  if (rot === 180) return { x: W - dx - dw, y: H - dy - dh, w: dw, h: dh };
  if (rot === 270) return { x: dy, y: H - dx - dw, w: dh, h: dw };
  return { x: dx, y: dy, w: dw, h: dh };
}

function videoContentRect(
  clientW: number,
  clientH: number,
  sw: number,
  sh: number,
  rot: number,
): ContentRect {
  if (sw === 0 || sh === 0) return { x: 0, y: 0, w: clientW, h: clientH };
  const tw = rot % 180 !== 0 ? clientH : clientW;
  const th = rot % 180 !== 0 ? clientW : clientH;
  const scale =
    rot % 180 !== 0
      ? Math.min(tw / sw, th / sh)
      : Math.max(tw / sw, th / sh);
  const dw = sw * scale;
  const dh = sh * scale;
  const dx = (tw - dw) / 2;
  const dy = (th - dh) / 2;
  if (rot === 90) return { x: clientW - dy - dh, y: dx, w: dh, h: dw };
  if (rot === 180) return { x: clientW - dx - dw, y: clientH - dy - dh, w: dw, h: dh };
  if (rot === 270) return { x: dy, y: clientH - dx - dw, w: dh, h: dw };
  return { x: dx, y: dy, w: dw, h: dh };
}

function iou(a: BoundingBox, b: BoundingBox): number {
  const ix0 = Math.max(a.x_min, b.x_min);
  const iy0 = Math.max(a.y_min, b.y_min);
  const ix1 = Math.min(a.x_max, b.x_max);
  const iy1 = Math.min(a.y_max, b.y_max);
  const inter = Math.max(0, ix1 - ix0) * Math.max(0, iy1 - iy0);
  if (inter <= 0) return 0;
  const areaA = Math.max(0, a.x_max - a.x_min) * Math.max(0, a.y_max - a.y_min);
  const areaB = Math.max(0, b.x_max - b.x_min) * Math.max(0, b.y_max - b.y_min);
  const union = areaA + areaB - inter;
  return union <= 0 ? 0 : inter / union;
}

const MAX_ZONE_POINTS = 64;
const ZONE_POINT_STEP = 0.008;
const MIN_ZONE_AREA = 0.001;

function polygonArea(pts: [number, number][]): number {
  let sum = 0;
  for (let i = 0; i < pts.length; i++) {
    const [x0, y0] = pts[i];
    const [x1, y1] = pts[(i + 1) % pts.length];
    sum += x0 * y1 - x1 * y0;
  }
  return Math.abs(sum) / 2;
}

function orientation(a: [number, number], b: [number, number], c: [number, number]): number {
  return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
}

function segmentsProperlyCross(
  a: [number, number],
  b: [number, number],
  c: [number, number],
  d: [number, number],
): boolean {
  const o1 = orientation(a, b, c);
  const o2 = orientation(a, b, d);
  const o3 = orientation(c, d, a);
  const o4 = orientation(c, d, b);
  return o1 * o2 < 0 && o3 * o4 < 0;
}

function polygonSelfIntersects(pts: [number, number][]): boolean {
  const n = pts.length;
  if (n < 4) return false;
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      // Neighboring edges share a vertex by construction; the first and
      // last edges do too once the outline is closed.
      if (j === i + 1 || (i === 0 && j === n - 1)) continue;
      if (segmentsProperlyCross(pts[i], pts[(i + 1) % n], pts[j], pts[(j + 1) % n])) {
        return true;
      }
    }
  }
  return false;
}

function drawOverlay(
  canvas: HTMLCanvasElement,
  video: HTMLVideoElement | null,
  objects: SceneObject[],
  violatingIds: Set<string>,
  zones: Zone[],
  draft: [number, number][] | null,
  rot: number,
): void {
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = (canvas.width = canvas.clientWidth || 640);
  const h = (canvas.height = canvas.clientHeight || 480);
  const live = !!video && video.readyState >= 2 && video.videoWidth > 0;
  if (!live) {
    // Black stage; the centered Start camera button is the call to action.
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, w, h);
    return;
  }
  const content = drawVideoFrame(ctx, video, w, h, rot);
  const X = (nx: number): number => content.x + nx * content.w;
  const Y = (ny: number): number => content.y + ny * content.h;
  for (const z of zones) {
    ctx.strokeStyle = "#f5a524";
    ctx.setLineDash([6, 4]);
    ctx.lineWidth = 2;
    ctx.beginPath();
    z.polygon.forEach(([px, py], i) => {
      if (i === 0) ctx.moveTo(X(px), Y(py));
      else ctx.lineTo(X(px), Y(py));
    });
    ctx.closePath();
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#f5a524";
    ctx.font = "12px monospace";
    ctx.fillText(z.name, X(z.polygon[0][0]) + 4, Y(z.polygon[0][1]) - 6);
  }
  if (draft && draft.length > 0) {
    ctx.strokeStyle = "#f5a524";
    ctx.lineWidth = 2;
    ctx.beginPath();
    draft.forEach(([px, py], i) => {
      if (i === 0) ctx.moveTo(X(px), Y(py));
      else ctx.lineTo(X(px), Y(py));
    });
    ctx.stroke();
  }
  // One physical object can appear as several overlapping scene entries (one
  // per rule selector). Paint every entry that overlaps a violating box red so
  // a red fill never ends up with a green outline on top of it.
  const violBoxes = objects.filter((o) => violatingIds.has(o.id)).map((o) => o.bbox);
  for (const o of objects) {
    const bad =
      violatingIds.has(o.id) || violBoxes.some((v) => iou(o.bbox, v) >= 0.5);
    const x = X(o.bbox.x_min);
    const y = Y(o.bbox.y_min);
    const bw = X(o.bbox.x_max) - X(o.bbox.x_min);
    const bh = Y(o.bbox.y_max) - Y(o.bbox.y_min);
    const contour = o.polygon && o.polygon.length >= 3 ? o.polygon : null;
    ctx.strokeStyle = bad ? "#e5484d" : "#35c26e";
    if (contour) {
      ctx.beginPath();
      contour.forEach(([px, py], i) => {
        if (i === 0) ctx.moveTo(X(px), Y(py));
        else ctx.lineTo(X(px), Y(py));
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
        ctx.fillRect(x, y, bw, bh);
      }
      ctx.lineWidth = bad ? 3 : 1.5;
      ctx.strokeRect(x, y, bw, bh);
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
  const [draft, setDraft] = useState<[number, number][] | null>(null);
  const [auto, setAuto] = useState(false);
  const [autoNote, setAutoNote] = useState("");
  const [cameras, setCameras] = useState<MediaDeviceInfo[]>([]);
  const [cameraId, setCameraId] = useState("");
  const [hasStream, setHasStream] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const sheetRef = useRef<HTMLDivElement>(null);
  const [sheetH, setSheetH] = useState(0);
  const grabDrag = useRef<{ startY: number; moved: boolean } | null>(null);
  const grabMoved = useRef(false);

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

  const refreshCameras = useCallback(async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      setCameras(devices.filter((d) => d.kind === "videoinput"));
    } catch {
      /* device labels need prior permission; list stays empty */
    }
  }, []);

  useEffect(() => {
    void refreshCameras();
    navigator.mediaDevices?.addEventListener?.("devicechange", () => void refreshCameras());
  }, [refreshCameras]);

  useEffect(() => {
    const el = sheetRef.current;
    if (!el) return;
    const update = (): void => setSheetH(el.offsetHeight);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const [resolution, setResolution] = useState("");
  const [sensorSize, setSensorSize] = useState<[number, number]>([0, 0]);
  const [rotation, setRotation] = useState<number>(() => {
    const saved = typeof window === "undefined" ? null : window.localStorage.getItem("wd-rotation");
    const n = saved === null ? 0 : Number(saved);
    return ROTATIONS.includes(n as (typeof ROTATIONS)[number]) ? n : 0;
  });

  useEffect(() => {
    try {
      window.localStorage.setItem("wd-rotation", String(rotation));
    } catch {
      /* private mode etc: rotation just won't persist */
    }
    setResolution((prev) => {
      if (sensorSize[0] === 0) return prev;
      return rotation % 180 !== 0
        ? `${sensorSize[1]}×${sensorSize[0]}`
        : `${sensorSize[0]}×${sensorSize[1]}`;
    });
  }, [rotation, sensorSize]);

  const startCamera = useCallback(
    async (deviceId?: string) => {
      setError("");
      try {
        const old = videoRef.current?.srcObject as MediaStream | null;
        old?.getTracks().forEach((t) => t.stop());
        const chosen = deviceId ?? cameraId;
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            // Camo exposes at most 1920x1080 landscape (verified: no
            // 1080x1920 portrait mode; portrait ideals pick a square crop).
            ...(chosen ? { deviceId: { exact: chosen } } : {}),
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
        });
        const v = videoRef.current;
        if (v) {
          v.srcObject = stream;
          await v.play();
        }
        setHasStream(true);
        setStatus((s) => (s === "idle" ? "capturing" : s));
        void refreshCameras();
      } catch (e) {
        setHasStream(false);
        setError(`Camera failed: ${e instanceof Error ? e.message : String(e)}`);
        setStatus("error");
      }
    },
    [cameraId, refreshCameras],
  );

  const stopCamera = useCallback((): void => {
    setAuto(false);
    const v = videoRef.current;
    const stream = v?.srcObject as MediaStream | null;
    stream?.getTracks().forEach((t) => t.stop());
    if (v) v.srcObject = null;
    setHasStream(false);
    setStatus("idle");
  }, []);

  const snapshotBase64 = useCallback((): string => {
    const v = videoRef.current;
    const c = snapRef.current;
    if (!v || !c || v.readyState < 2 || v.videoWidth === 0) return "";
    // Upright full-frame snapshot (same orientation as the overlay coords).
    const swap = rotation % 180 !== 0;
    c.width = swap ? v.videoHeight : v.videoWidth;
    c.height = swap ? v.videoWidth : v.videoHeight;
    const ctx = c.getContext("2d");
    if (!ctx) return "";
    drawVideoFrame(ctx, v, c.width, c.height, rotation);
    const url = c.toDataURL("image/jpeg", 0.8);
    return url.includes(",") ? url.split(",")[1] : "";
  }, [rotation]);

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
    let raf = 0;
    const frame = (): void => {
      drawOverlay(c, v, objects, viol, zones, draft, rotation);
      raf = window.requestAnimationFrame(frame);
    };
    raf = window.requestAnimationFrame(frame);
    return () => window.cancelAnimationFrame(raf);
  }, [objects, violations, zones, draft, rotation]);

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
    const v = videoRef.current;
    if (!c) return { x: 0, y: 0 };
    const r = c.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * c.clientWidth;
    const py = ((e.clientY - r.top) / r.height) * c.clientHeight;
    const content = videoContentRect(
      c.clientWidth,
      c.clientHeight,
      v?.videoWidth ?? 0,
      v?.videoHeight ?? 0,
      rotation,
    );
    return {
      x: Math.min(1, Math.max(0, (px - content.x) / content.w)),
      y: Math.min(1, Math.max(0, (py - content.y) / content.h)),
    };
  };

  return (
    <>
      <div className="stage">
        <video
          ref={videoRef}
          muted
          playsInline
          autoPlay
          style={{ display: "none" }}
          onPlaying={(e) => {
            const v = e.currentTarget;
            if (v.videoWidth > 0) {
              setSensorSize([v.videoWidth, v.videoHeight]);
              setResolution(
                rotation % 180 !== 0
                  ? `${v.videoHeight}×${v.videoWidth}`
                  : `${v.videoWidth}×${v.videoHeight}`,
              );
            }
          }}
        />
        <canvas
          ref={canvasRef}
          className="overlay"
          onMouseDown={(e) => {
            if (!drawing) return;
            const p = canvasPos(e);
            setError("");
            setDraft([[p.x, p.y]]);
          }}
          onMouseMove={(e) => {
            if (!drawing || !draft) return;
            const p = canvasPos(e);
            const last = draft[draft.length - 1];
            const dx = p.x - last[0];
            const dy = p.y - last[1];
            if (dx * dx + dy * dy < ZONE_POINT_STEP * ZONE_POINT_STEP) return;
            if (draft.length >= MAX_ZONE_POINTS * 4) return;
            setDraft([...draft, [p.x, p.y]]);
          }}
          onMouseUp={() => {
            if (!drawing || !draft) return;
            const finish = (message: string): void => {
              setError(message);
              setDraft(null);
            };
            if (draft.length < 3 || polygonArea(draft) < MIN_ZONE_AREA) {
              finish("Zone is too small. Draw a larger outline.");
              return;
            }
            if (polygonSelfIntersects(draft)) {
              finish("Zone lines must not cross. Draw a simple outline without crossing lines.");
              return;
            }
            // Evenly thin the trail to a bounded point count.
            let poly: [number, number][] = draft;
            if (poly.length > MAX_ZONE_POINTS) {
              const step = poly.length / MAX_ZONE_POINTS;
              poly = Array.from(
                { length: MAX_ZONE_POINTS },
                (_, i) => poly[Math.min(poly.length - 1, Math.floor(i * step))],
              );
            }
            const name = zoneName.trim() || "zone";
            setZones((prev) => [...prev.filter((z) => z.id !== name), { id: name, name, polygon: poly }]);
            setError("");
            setDraft(null);
            setDrawing(false);
          }}
        />
      </div>
      <canvas ref={snapRef} style={{ display: "none" }} />
      {!hasStream && (
        <div className="center-start">
          <button className="primary big" onClick={() => void startCamera()}>
            Start camera
          </button>
        </div>
      )}

      <div className="brand">
        <h1>WorldDebugger</h1>
        <span className="tagline">Debug the physical world.</span>
      </div>
      <div className="top-right">
        <span className={`status-pill ${status}`}>{status}</span>
      </div>

      <div className="toasts" style={{ bottom: sheetH > 0 ? sheetH + 12 : undefined }}>
        {error && <div className="toast">{error}</div>}
        {autoNote && !auto && <div className="toast">{autoNote}</div>}
        {violations.slice(0, 2).map((v, i) => (
          <div key={`${v.rule_id}-${i}`} className="toast">
            <strong>⚠ {v.rule_name}</strong>
            {v.message}
          </div>
        ))}
        {resolvedFlash && violations.length === 0 && <div className="toast ok">✓ Resolved</div>}
      </div>

      <div ref={sheetRef} className={`sheet${sheetOpen ? " open" : ""}`}>
        <div
          className="grabber"
          title={sheetOpen ? "Pull down to close" : "Pull up for rules"}
          onClick={() => {
            if (grabMoved.current) {
              grabMoved.current = false;
              return;
            }
            setSheetOpen((o) => !o);
          }}
          onPointerDown={(e) => {
            try {
              e.currentTarget.setPointerCapture(e.pointerId);
            } catch {
              /* no capture support: drag still works while over the grabber */
            }
            grabDrag.current = { startY: e.clientY, moved: false };
          }}
          onPointerMove={(e) => {
            const d = grabDrag.current;
            if (!d) return;
            const dy = e.clientY - d.startY;
            if (Math.abs(dy) > 48) {
              d.moved = true;
              setSheetOpen(dy < 0);
            }
          }}
          onPointerUp={() => {
            grabMoved.current = grabDrag.current?.moved ?? false;
            grabDrag.current = null;
          }}
          onPointerCancel={() => {
            grabDrag.current = null;
          }}
        />
        <div className="dock">
          <button className="primary" onClick={() => void runAnalyze()}>
            Analyze
          </button>
          <label className="toggle" title="Auto analyze every 2s (stops after 3 min)">
            <input
              type="checkbox"
              checked={auto}
              onChange={() => setAuto((a) => !a)}
            />
            <span className="track" />
            Auto
          </label>
          <button className={drawing ? "on" : ""} onClick={() => {
            setDrawing((d) => !d);
            setDraft(null);
          }}>
            {drawing ? "Drawing… trace an outline" : "Draw zone"}
          </button>
        </div>
        <div className="sheet-body">
          <div className="sheet-content">
            <h2>Camera{resolution && <span className="meta-inline"> · {resolution}</span>}</h2>
            <div className="row">
              {cameras.length > 1 ? (
                <select
                  value={cameraId}
                  onChange={(e) => {
                    setCameraId(e.target.value);
                    void startCamera(e.target.value);
                  }}
                  title="Camera"
                >
                  <option value="">Default camera</option>
                  {cameras.map((c, i) => (
                    <option key={c.deviceId || i} value={c.deviceId}>
                      {c.label || `Camera ${i + 1}`}
                    </option>
                  ))}
                </select>
              ) : (
                <span className="hint">Single camera found.</span>
              )}
              <button
                className={rotation !== 0 ? "on" : ""}
                title="Rotate preview (for sideways-mounted cameras)"
                onClick={() => {
                  const i = ROTATIONS.indexOf(rotation as (typeof ROTATIONS)[number]);
                  setRotation(ROTATIONS[(i + 1) % ROTATIONS.length]);
                }}
              >
                ⟳ {rotation}°
              </button>
              <button onClick={() => void startCamera()}>Restart camera</button>
              {hasStream && <button onClick={stopCamera}>Stop camera</button>}
            </div>
            <h2>Rules</h2>
        <div className="row">
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
            <div className="meta">detects: {r.selectors.map((s) => s.sam_prompt).join(", ")}</div>
            {r.condition.requires_metric_depth && (
              <div className="error">Needs metric depth — not available in this MVP.</div>
            )}
          </div>
        ))}
        {rules.length === 0 && <p className="hint">No rules yet. Try “Keep drinks away from laptops.”</p>}

        <h2>Zones</h2>
        <div className="row">
          <input
            type="text"
            value={zoneName}
            onChange={(e) => setZoneName(e.target.value)}
            placeholder="zone name"
          />
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          {zones.length === 0 && <span className="hint">No zones. Use Draw zone, then drag on the video.</span>}
          {zones.map((z) => (
            <span key={z.id} className="zone-chip">
              {z.name}
              <button onClick={() => setZones((prev) => prev.filter((x) => x.id !== z.id))}>×</button>
            </span>
          ))}
        </div>

        <h2>Issues</h2>
        {violations.map((v, i) => (
          <div key={`${v.rule_id}-${i}`} className="issue">
            <div className="title">⚠ {v.rule_name}</div>
            <div>{v.message}</div>
            <div className="time">Detected just now</div>
          </div>
        ))}
        {violations.length === 0 && <div className="ok-line">✓ No violations</div>}
        {resolvedFlash && <div className="resolved-toast">✓ Resolved</div>}

        <h2>Detected objects</h2>
        {objects.length === 0 && <p className="hint">Nothing detected in the last frame.</p>}
        {objects.map((o) => (
          <div key={o.id} className="detect-line">
            {o.concept} {Math.round(o.confidence * 100)}% [{o.bbox.x_min.toFixed(2)},{" "}
            {o.bbox.y_min.toFixed(2)}, {o.bbox.x_max.toFixed(2)}, {o.bbox.y_max.toFixed(2)}]
          </div>
        ))}

        <h2>Demo without camera</h2>
        <div className="row">
          <button onClick={() => void runAnalyze("default")}>Simulate: drink near laptop</button>
          <button onClick={() => void runAnalyze("far")}>Simulate: drink moved away</button>
        </div>
        <p className="hint">Fixture frames for the Demo 1 violation → Resolved flow.</p>

        <div className="foot">Powered by Muse Spark 1.3 + SAM 3.1{mocked ? " · Mock mode" : ""}</div>
          </div>
        </div>
      </div>
    </>
  );
}
