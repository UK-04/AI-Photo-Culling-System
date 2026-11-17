import { imageUrl } from "../api";
import { burstFrames, effectiveLabel, percent } from "../logic";
import { useStore } from "../store";

/** Up to four frames of the selected photo's burst, side by side. P and X act on the highlighted one. */
export function Compare() {
  const { photos, selectedId, select } = useStore();
  const current = photos.find((p) => p.id === selectedId);
  const all = burstFrames(photos, current?.burst_id ?? null);
  if (!current || all.length < 2) return <div className="empty"><p>Select a photo that is part of a burst to compare its frames.</p></div>;

  // A window of four that always contains the selected frame.
  const index = all.findIndex((p) => p.id === current.id);
  const start = Math.max(0, Math.min(index - 1, all.length - 4));
  const frames = all.slice(start, start + 4);

  return (
    <div className="compare" style={{ gridTemplateColumns: `repeat(${frames.length <= 2 ? frames.length : 2}, 1fr)` }}>
      {frames.map((p) => {
        const label = effectiveLabel(p);
        return (
          <button key={p.id} className={`compare-frame${p.id === selectedId ? " is-selected" : ""}`} onClick={() => select(p.id)}>
            <img src={imageUrl(p, "preview")} alt={p.name} draggable={false} />
            <span className="compare-caption">
              {label && <span className={`dot dot-${label.toLowerCase()}`} />}
              <span>{p.burst_rank === 0 ? "Best frame" : `Frame ${(p.burst_rank ?? 0) + 1}`}</span>
              <span className="muted">Sharpness {percent(p.sharp_pct)}</span>
              {p.user_label && <span className="muted">{p.user_label === "KEEP" ? "Picked" : "Rejected"}</span>}
            </span>
          </button>
        );
      })}
      {all.length > 4 && <p className="compare-note">Showing {frames.length} of {all.length} frames. Use the arrow keys to move through the burst.</p>}
    </div>
  );
}
