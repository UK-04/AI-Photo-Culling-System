export type Label = "KEEP" | "REVIEW" | "REJECT";
export type UserLabel = "KEEP" | "REJECT" | null;

export interface Photo {
  id: number;
  name: string;
  path: string;
  file_hash: string | null;
  captured_at: string | null;
  capture_ts: number | null;
  width: number | null;
  height: number | null;
  burst_id: number | null;
  burst_rank: number | null;
  burst_size: number;
  user_label: UserLabel;
  user_rating: number;
  status: "done" | "error";
  error: string | null;
  label: Label | null;
  confidence: number | null;
  final_score: number | null;
  rule_score: number | null;
  personal_score: number | null;
  reason_primary: string | null;
  reason_secondary: string | null;
  sharp_pct: number | null;
  face_count: number | null;
}

export interface Face {
  box_rel: [number, number, number, number];
  main: boolean;
  eye_open: number | null;
  eyes_closed: boolean | null;
}

export interface PhotoDetail extends Photo {
  camera: string | null;
  lens: string | null;
  iso: number | null;
  shutter_text: string | null;
  aperture: number | null;
  focal: number | null;
  sharpness: number | null;
  subject_sharpness: number | null;
  blur_kind: string | null;
  exposure_mean: number | null;
  clip_high_pct: number | null;
  clip_low_pct: number | null;
  eyes_closed_count: number | null;
  main_eyes_closed: number | null;
  face_backend: string | null;
  faces: Face[];
}

export interface Counts {
  total: number;
  keep: number;
  review: number;
  reject: number;
  undecided: number;
  picked: number;
  rejected: number;
  rated3: number;
  errors: number;
}

export interface Progress {
  shoot_id: number;
  stage: string;
  done: number;
  total: number;
  errors: number;
  message: string;
  running: boolean;
  elapsed: number;
}

export interface Shoot {
  id: number;
  name: string;
  folder_path: string;
  status: string;
  photo_count: number;
  finished_at: string | null;
  counts: Counts;
  progress: Progress;
}

export interface ModelStatus {
  decisions: number;
  needed: number;
  ready: boolean;
  embedder: string | null;
  face_backend: string;
  model: null | {
    version: string;
    kind: string;
    n_decisions: number;
    n_shoots: number;
    metrics: { accuracy?: number; rules_accuracy?: number };
  };
  training: { running: boolean; last: null | { status: string; message: string } };
}

export type Filter = "all" | "keep" | "review" | "reject" | "undecided" | "picked" | "rated3" | "teach";
export type Sort = "time" | "score" | "sharpness";
export type View = "grid" | "loupe" | "compare";
