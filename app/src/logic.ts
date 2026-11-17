// Pure functions the UI is built on. No React, no network: easy to test.
import type { Counts, Filter, Label, Photo, Sort } from "./types";

/** The photographer's decision when there is one, otherwise the engine's recommendation. */
export function effectiveLabel(p: Photo): Label | null {
  return p.user_label ?? p.label;
}

export function matchesFilter(p: Photo, filter: Filter, teachIds?: Set<number>): boolean {
  switch (filter) {
    case "all":
      return true;
    case "keep":
      return effectiveLabel(p) === "KEEP";
    case "review":
      return p.user_label === null && p.label === "REVIEW";
    case "reject":
      return effectiveLabel(p) === "REJECT";
    case "undecided":
      return p.user_label === null && p.status === "done";
    case "picked":
      return p.user_label === "KEEP";
    case "rated3":
      return p.user_rating >= 3;
    case "teach":
      return teachIds?.has(p.id) ?? false;
  }
}

export function countPhotos(photos: Photo[]): Counts {
  const c: Counts = { total: photos.length, keep: 0, review: 0, reject: 0, undecided: 0, picked: 0, rejected: 0, rated3: 0, errors: 0 };
  for (const p of photos) {
    const eff = effectiveLabel(p);
    if (eff === "KEEP") c.keep++;
    if (eff === "REJECT") c.reject++;
    if (p.user_label === null && p.label === "REVIEW") c.review++;
    if (p.user_label === null) c.undecided++;
    if (p.user_label === "KEEP") c.picked++;
    if (p.user_label === "REJECT") c.rejected++;
    if (p.user_rating >= 3) c.rated3++;
    if (p.status === "error") c.errors++;
  }
  return c;
}

export function sortPhotos(photos: Photo[], sort: Sort): Photo[] {
  if (sort === "time") return photos;
  const key = sort === "score" ? (p: Photo) => p.final_score ?? -1 : (p: Photo) => p.sharp_pct ?? -1;
  return [...photos].sort((a, b) => key(b) - key(a));
}

/**
 * What the grid shows: photos passing the filter, with each burst collapsed to a
 * single cell (its best frame that passes) unless that burst is expanded.
 */
export function visiblePhotos(
  photos: Photo[],
  filter: Filter,
  sort: Sort,
  expanded: Set<number>,
  teachIds?: Set<number>,
): Photo[] {
  const passing = photos.filter((p) => matchesFilter(p, filter, teachIds));
  const lead = new Map<number, Photo>();
  for (const p of passing) {
    if (p.burst_id === null || expanded.has(p.burst_id)) continue;
    const current = lead.get(p.burst_id);
    if (!current || (p.burst_rank ?? 0) < (current.burst_rank ?? 0)) lead.set(p.burst_id, p);
  }
  const shown = passing.filter((p) => p.burst_id === null || expanded.has(p.burst_id) || lead.get(p.burst_id) === p);
  return sortPhotos(shown, sort);
}

/** Frames of one burst, best first. */
export function burstFrames(photos: Photo[], burstId: number | null): Photo[] {
  if (burstId === null) return [];
  return photos.filter((p) => p.burst_id === burstId).sort((a, b) => (a.burst_rank ?? 0) - (b.burst_rank ?? 0));
}

/** Index of the next photo after `from` that still needs a decision (wraps around). */
export function nextNeedingReview(list: Photo[], from: number): number {
  for (let step = 1; step <= list.length; step++) {
    const i = (from + step) % list.length;
    const p = list[i];
    if (p.user_label === null && p.status === "done" && p.label !== "KEEP") return i;
  }
  return -1;
}

export function percent(v: number | null | undefined): string {
  return v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`;
}

export function formatTime(iso: string | null): string {
  if (!iso) return "";
  const [date, time] = iso.split("T");
  return `${date}  ${(time ?? "").slice(0, 8)}`;
}

const STAGE_TEXT: Record<string, string> = {
  queued: "Waiting to start",
  discovering: "Looking for photos",
  analyzing: "Analyzing photos",
  embedding: "Comparing photos",
  grouping: "Grouping bursts",
  scoring: "Scoring",
};

export function stageText(stage: string, message: string): string {
  return message || STAGE_TEXT[stage] || "";
}
