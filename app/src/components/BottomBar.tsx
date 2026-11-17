import { useMemo } from "react";
import { countPhotos, percent, stageText } from "../logic";
import { useStore } from "../store";

export function BottomBar() {
  const { photos, progress, model, cancelScan, rescan } = useStore();
  const counts = useMemo(() => countPhotos(photos), [photos]);
  const running = progress?.running ?? false;
  const share = progress && progress.total > 0 ? progress.done / progress.total : null;

  let learning = "";
  if (model) {
    if (model.training.running) learning = "Learning from your decisions…";
    else if (model.model) {
      const acc = model.model.metrics.accuracy;
      learning = `Knows your taste from ${model.model.n_decisions} decisions${acc ? `, agrees ${percent(acc)}` : ""}`;
    } else learning = `Learning your taste: ${model.decisions} of ${model.needed} decisions`;
  }

  return (
    <footer className="bottombar">
      <div className="bottombar-left">
        {running ? (
          <>
            <span className="progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={share === null ? undefined : Math.round(share * 100)}>
              <span className={share === null ? "progress-fill is-indeterminate" : "progress-fill"} style={share === null ? undefined : { width: `${share * 100}%` }} />
            </span>
            <span>
              {stageText(progress!.stage, progress!.message)}
              {progress!.total > 0 && ` ${progress!.done} of ${progress!.total}`}
            </span>
            <button className="link" onClick={() => void cancelScan()}>Pause</button>
          </>
        ) : progress?.stage === "error" ? (
          <span className="error-text">{progress.message}</span>
        ) : progress?.stage === "cancelled" ? (
          <>
            <span>Scan paused.</span>
            <button className="link" onClick={() => void rescan()}>Resume</button>
          </>
        ) : (
          <span>
            {counts.total} photos
            {counts.total > 0 && `, ${counts.picked} picked, ${counts.rejected} rejected, ${counts.undecided - counts.errors} to go`}
            {counts.errors > 0 && `, ${counts.errors} unreadable`}
          </span>
        )}
      </div>
      <div className="bottombar-right" title={model ? `Faces: ${model.face_backend}. Similarity: ${model.embedder ?? "not loaded yet"}.` : undefined}>
        {learning}
      </div>
    </footer>
  );
}
