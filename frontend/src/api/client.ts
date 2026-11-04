import type { VisualRule, Violation, SceneObject, Zone } from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return (await resp.json()) as T;
}

export function compileRule(
  text: string,
): Promise<{ rule: VisualRule; mocked: boolean }> {
  return request("/api/rules/compile", {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export function listRules(): Promise<{ rules: VisualRule[] }> {
  return request("/api/rules");
}

export function deleteRule(ruleId: string): Promise<{ deleted: string }> {
  return request(`/api/rules/${ruleId}`, { method: "DELETE" });
}

export interface AnalyzeResult {
  scene: { objects: SceneObject[] };
  violations: Violation[];
  mocked: boolean;
  rule_ids: string[];
}

export function analyzeFrame(args: {
  imageBase64: string;
  imageVariant?: string;
  zones: Zone[];
}): Promise<AnalyzeResult> {
  return request("/api/analyze", {
    method: "POST",
    body: JSON.stringify({
      image_base64: args.imageBase64,
      image_variant: args.imageVariant ?? "default",
      zones: args.zones,
    }),
  });
}

export function health(): Promise<{ status: string; mock_meta_api: boolean }> {
  return request("/api/health");
}
