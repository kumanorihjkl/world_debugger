export type Status =
  | "idle"
  | "capturing"
  | "analyzing"
  | "safe"
  | "violation"
  | "error";

export interface BoundingBox {
  x_min: number;
  y_min: number;
  x_max: number;
  y_max: number;
}

export interface SceneObject {
  id: string;
  concept: string;
  selector_id: string;
  bbox: BoundingBox;
  confidence: number;
  centroid: [number, number];
  polygon: [number, number][] | null;
}

export interface Violation {
  rule_id: string;
  rule_name: string;
  severity: string;
  message: string;
  object_ids: string[];
  timestamp: number;
}

export interface Selector {
  id: string;
  concept: string;
  sam_prompt: string;
}

export interface VisualRule {
  id: string;
  name: string;
  original_text: string;
  description: string;
  severity: string;
  selectors: Selector[];
  condition: {
    operator: string;
    subject: string;
    object?: string | null;
    threshold: number;
    zone_id?: string | null;
    duration_seconds?: number | null;
    requires_metric_depth: boolean;
  };
  explanation: string;
}

export interface Zone {
  id: string;
  name: string;
  polygon: [number, number][];
}
