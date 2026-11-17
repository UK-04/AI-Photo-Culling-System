import { describe, expect, it } from "vitest";
import {
  burstFrames, categoryCounts, clampPan, countPhotos, effectiveLabel, matchesFilter, nextNeedingReview, scaleForLevel, stepZoomLevel, visiblePhotos,
} from "./logic";
import type { Photo } from "./types";

function photo(id: number, over: Partial<Photo> = {}): Photo {
  return {
    id, name: `IMG_${id}.jpg`, path: `/x/IMG_${id}.jpg`, file_hash: "h", captured_at: null, capture_ts: id,
    width: 100, height: 100, burst_id: null, burst_rank: null, burst_size: 1, user_label: null, user_rating: 0,
    status: "done", error: null, label: "KEEP", confidence: 0.8, final_score: 0.7, rule_score: 0.7,
    personal_score: null, reason_primary: "Sharp", reason_secondary: null, sharp_pct: 0.5, face_count: 0,
    rotation: 0, recover_score: 1, recover_label: "Nothing to fix", recover_note: "",
    category: null, category_confidence: null, relevance: null, off_topic: 0, ...over,
  };
}

const photos = [
  photo(1),
  photo(2, { label: "REVIEW" }),
  photo(3, { label: "REJECT" }),
  photo(4, { label: "REJECT", user_label: "KEEP", user_rating: 4 }),
  photo(5, { label: "KEEP", user_label: "REJECT" }),
  photo(6, { burst_id: 9, burst_rank: 0, burst_size: 3 }),
  photo(7, { burst_id: 9, burst_rank: 1, burst_size: 3, label: "REVIEW" }),
  photo(8, { burst_id: 9, burst_rank: 2, burst_size: 3, label: "REVIEW" }),
];

describe("labels and filters", () => {
  it("the photographer's decision wins over the engine's", () => {
    expect(effectiveLabel(photos[3])).toBe("KEEP");
    expect(effectiveLabel(photos[4])).toBe("REJECT");
    expect(effectiveLabel(photos[1])).toBe("REVIEW");
  });

  it("filters match the sidebar counts", () => {
    const counts = countPhotos(photos);
    for (const f of ["keep", "review", "reject", "picked", "rated3"] as const) {
      expect(photos.filter((p) => matchesFilter(p, f)).length).toBe(counts[f]);
    }
    expect(counts).toMatchObject({ total: 8, keep: 3, review: 3, reject: 2, undecided: 6, picked: 1, rejected: 1, rated3: 1 });
  });

  it("the teach filter uses the queue from the engine", () => {
    expect(photos.filter((p) => matchesFilter(p, "teach", new Set([2, 7]))).map((p) => p.id)).toEqual([2, 7]);
  });
});

describe("burst stacks", () => {
  it("collapses a burst to its best frame", () => {
    expect(visiblePhotos(photos, "all", "time", new Set()).map((p) => p.id)).toEqual([1, 2, 3, 4, 5, 6]);
  });

  it("shows every frame of an expanded burst", () => {
    expect(visiblePhotos(photos, "all", "time", new Set([9])).map((p) => p.id)).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });

  it("a filter that hides the best frame still shows one frame of the burst", () => {
    expect(visiblePhotos(photos, "review", "time", new Set()).map((p) => p.id)).toEqual([2, 7]);
  });

  it("lists burst frames best first", () => {
    expect(burstFrames([photos[7], photos[5], photos[6]], 9).map((p) => p.id)).toEqual([6, 7, 8]);
    expect(burstFrames(photos, null)).toEqual([]);
  });

  it("sorts by score", () => {
    const list = [photo(1, { final_score: 0.2 }), photo(2, { final_score: 0.9 }), photo(3, { final_score: null })];
    expect(visiblePhotos(list, "all", "score", new Set()).map((p) => p.id)).toEqual([2, 1, 3]);
  });
});

describe("next photo needing review", () => {
  it("skips decided photos and engine keeps, and wraps around", () => {
    expect(nextNeedingReview(photos, 0)).toBe(1);
    expect(nextNeedingReview(photos, 2)).toBe(6);
    expect(nextNeedingReview(photos, 7)).toBe(1);
    expect(nextNeedingReview([photo(1), photo(2, { user_label: "KEEP" })], 0)).toBe(-1);
  });
});


describe("loupe zoom", () => {
  // a 6000x4000 photo in a 1200x800 box fits at 0.2 screen px per image px
  const fit = 0.2, fitW = 1200, fitH = 800;

  it("100% shows one image pixel per screen pixel", () => {
    expect(scaleForLevel("1", fit, fitW, fitH, 1200, 800)).toBe(5);
    expect(scaleForLevel("2", fit, fitW, fitH, 1200, 800)).toBe(10);
    expect(scaleForLevel("0.5", fit, fitW, fitH, 1200, 800)).toBe(2.5);
  });

  it("fill covers the box", () => {
    // a portrait photo (fit 400x600) in a 900x600 box must grow to fill the width
    expect(scaleForLevel("fill", 0.1, 400, 600, 900, 600)).toBe(2.25);
  });

  it("panning cannot pull the photo off the edge", () => {
    expect(clampPan(50, 3000, 1000)).toBe(0); // left edge stays at or left of 0
    expect(clampPan(-5000, 3000, 1000)).toBe(-2000); // right edge stays at or right of the box
    expect(clampPan(-700, 3000, 1000)).toBe(-700);
    expect(clampPan(123, 600, 1000)).toBe(200); // smaller than the box: centred
  });

  it("steps through the zoom levels and stops at the ends", () => {
    expect(stepZoomLevel("1", 1)).toBe("2");
    expect(stepZoomLevel("1", -1)).toBe("0.5");
    expect(stepZoomLevel("4", 1)).toBe("4");
    expect(stepZoomLevel("fill", -1)).toBe("fill");
  });
});

describe("topics", () => {
  const list = [
    photo(1, { category: "Group photos" }),
    photo(2, { category: "Details", off_topic: 1 }),
    photo(3, { category: "Group photos", label: "REJECT" }),
    photo(4, { category: null }),
  ];

  it("counts categories, biggest first", () => {
    expect(categoryCounts(list)).toEqual([{ name: "Group photos", count: 2 }, { name: "Details", count: 1 }]);
  });

  it("a topic narrows whatever filter is active", () => {
    expect(visiblePhotos(list, "all", "time", new Set(), undefined, "Group photos").map((p) => p.id)).toEqual([1, 3]);
    expect(visiblePhotos(list, "reject", "time", new Set(), undefined, "Group photos").map((p) => p.id)).toEqual([3]);
    expect(visiblePhotos(list, "offtopic", "time", new Set()).map((p) => p.id)).toEqual([2]);
  });
});
