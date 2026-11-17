import { useEffect, useState } from "react";
import { api } from "../api";
import { effectiveLabel, formatTime, percent } from "../logic";
import { useStore } from "../store";
import type { PhotoDetail } from "../types";

const REJECT_REASONS = ["focus", "eyes", "expression", "exposure", "duplicate", "composition", "other"];
const LABEL_TEXT = { KEEP: "Keep", REVIEW: "Review", REJECT: "Reject" } as const;

function Meter({ name, value, hint }: { name: string; value: number | null | undefined; hint?: string }) {
  const v = value === null || value === undefined ? null : Math.max(0, Math.min(1, value));
  return (
    <div className="meter" title={hint}>
      <span className="meter-name">{name}</span>
      <span className="meter-track"><span className="meter-fill" style={{ width: v === null ? 0 : `${v * 100}%` }} /></span>
      <span className="meter-value">{v === null ? "–" : Math.round(v * 100)}</span>
    </div>
  );
}

export function Inspector() {
  const { photos, selectedId, decide, rotate } = useStore();
  const photo = photos.find((p) => p.id === selectedId);
  const [detail, setDetail] = useState<PhotoDetail | null>(null);

  useEffect(() => {
    setDetail(null);
    if (selectedId === null) return;
    let live = true;
    api.photo(selectedId).then((d) => live && setDetail(d)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [selectedId]);

  if (!photo) return <aside className="inspector"><p className="muted">No photo selected.</p></aside>;

  const label = effectiveLabel(photo);
  const overridden = photo.user_label !== null && photo.label !== null && photo.user_label !== photo.label;
  const exif = detail
    ? [detail.camera, detail.lens, detail.focal ? `${Math.round(detail.focal)} mm` : null, detail.aperture ? `f/${detail.aperture}` : null, detail.shutter_text, detail.iso ? `ISO ${detail.iso}` : null].filter(Boolean)
    : [];

  return (
    <aside className="inspector" aria-label="Inspector">
      <section>
        <div className="verdict">
          {label ? <span className={`pill pill-${label.toLowerCase()}`}>{LABEL_TEXT[label]}</span> : <span className="pill">Not analyzed</span>}
          <span className="muted">
            {photo.user_label !== null ? "Your decision" : photo.confidence !== null ? `${percent(photo.confidence)} confident` : ""}
          </span>
        </div>
        {photo.status === "error" ? (
          <p className="reason">{photo.error}</p>
        ) : (
          <>
            <p className="reason">{photo.reason_primary}</p>
            {photo.reason_secondary && <p className="reason reason-second">{photo.reason_secondary}</p>}
            {overridden && <p className="muted small">Culler suggested {LABEL_TEXT[photo.label!].toLowerCase()}.</p>}
          </>
        )}
      </section>

      <section>
        <div className="actions">
          <button className={`button${photo.user_label === "KEEP" ? " is-keep" : ""}`} onClick={() => decide({ label: "KEEP" })}>Pick <kbd>P</kbd></button>
          <button className={`button${photo.user_label === "REJECT" ? " is-reject" : ""}`} onClick={() => decide({ label: "REJECT" })}>Reject <kbd>X</kbd></button>
          <button className="button" onClick={() => decide({ label: null })} disabled={photo.user_label === null}>Unflag <kbd>U</kbd></button>
        </div>
        <div className="rating" role="group" aria-label="Star rating">
          {[1, 2, 3, 4, 5].map((n) => (
            <button key={n} className={n <= photo.user_rating ? "is-on" : ""} onClick={() => decide({ rating: photo.user_rating === n ? 0 : n })} aria-label={`${n} star${n > 1 ? "s" : ""}`}>
              ★
            </button>
          ))}
        </div>
        <div className="actions rotate-actions">
          <button className="button" onClick={() => void rotate(-90)} disabled={photo.status !== "done"} title="Rotate left ([)">↺ Rotate left</button>
          <button className="button" onClick={() => void rotate(90)} disabled={photo.status !== "done"} title="Rotate right (])">Rotate right ↻</button>
        </div>
        {photo.user_label === "REJECT" && (
          <div className="chips">
            <span className="muted small">Why? It helps Culler learn.</span>
            <div>
              {REJECT_REASONS.map((r) => (
                <button key={r} className="chip" onClick={() => void api.decide([photo.id], { label: "REJECT", reason: r }).then(() => useStore.getState().notify(`Noted: ${r}`))}>
                  {r}
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      {photo.status === "done" && (
        <section>
          <h2>Scores</h2>
          <Meter name="Overall" value={photo.final_score} hint="What Culler ranks by" />
          <Meter name="Sharpness" value={photo.sharp_pct} hint="Rank within this shoot: 100 is the sharpest photo" />
          {photo.personal_score !== null && <Meter name="Your taste" value={photo.personal_score} hint="How likely you are to keep it, learned from your decisions" />}
          {detail && (
            <dl className="facts">
              <dt>Faces</dt>
              <dd>
                {detail.face_count
                  ? `${detail.face_count}${detail.main_eyes_closed === 1 ? ", main eyes closed" : detail.main_eyes_closed === 0 ? ", eyes open" : ", eyes not checked"}`
                  : "None found"}
              </dd>
              <dt>Blur</dt>
              <dd>{{ none: "None", shake: "Camera shake", missed_focus: "Focus elsewhere", soft: "Soft" }[detail.blur_kind ?? "none"] ?? "–"}</dd>
              <dt>Highlights</dt>
              <dd>{detail.clip_high_pct !== null ? `${detail.clip_high_pct.toFixed(1)}% clipped` : "–"}</dd>
              <dt>Shadows</dt>
              <dd>{detail.clip_low_pct !== null ? `${detail.clip_low_pct.toFixed(1)}% clipped` : "–"}</dd>
            </dl>
          )}
        </section>
      )}

      {photo.status === "done" && photo.recover_score !== null && (
        <section>
          <h2>Editing</h2>
          {photo.recover_score >= 1 ? (
            <p className="muted">Nothing needs fixing.</p>
          ) : (
            <>
              <p className="recover-label">{photo.recover_label}</p>
              <Meter name="Recoverable" value={photo.recover_score} hint="An estimate of how well editing can fix this photo's problems" />
              <p className="muted small">{photo.recover_note}</p>
            </>
          )}
        </section>
      )}

      {photo.status === "done" && photo.category && (
        <section>
          <h2>Topic</h2>
          <p className="recover-label">{photo.category}</p>
          {photo.relevance !== null && (
            <Meter name="Relevance" value={photo.relevance} hint="How much this photo belongs with the rest of the shoot. 100 means the shoot is full of photos like it." />
          )}
          {photo.off_topic ? <p className="muted small">Unlike the rest of this shoot.</p> : null}
        </section>
      )}

      <section>
        <h2>File</h2>
        <p className="filename">{photo.name}</p>
        <p className="muted small">{formatTime(photo.captured_at)}</p>
        {photo.width && <p className="muted small">{photo.width} × {photo.height}</p>}
        {exif.length > 0 && <p className="muted small">{exif.join(", ")}</p>}
      </section>
    </aside>
  );
}
