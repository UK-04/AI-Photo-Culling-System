import { useStore } from "../store";

/** Shown across the top when a newer version of Culler has been published. */
export function UpdateBanner() {
  const { update, installUpdate, set } = useStore();
  if (!update) return null;
  const percent = update.progress === null ? null : Math.round(update.progress * 100);
  return (
    <div className="update-banner" role="status">
      {update.state === "available" && (
        <>
          <span><strong>Culler {update.version} is available.</strong>{update.notes ? ` ${update.notes.split("\n")[0]}` : ""}</span>
          <span className="update-actions">
            <button className="button button-primary" onClick={() => void installUpdate()}>Update and restart</button>
            <button className="link" onClick={() => set({ update: null })}>Later</button>
          </span>
        </>
      )}
      {update.state === "installing" && (
        <span>
          Downloading Culler {update.version}{percent === null ? "…" : ` (${percent}%)`}. Culler restarts when it is ready; your decisions are already saved.
        </span>
      )}
      {update.state === "failed" && (
        <>
          <span className="error-text">The update could not be installed: {update.error}</span>
          <span className="update-actions">
            <button className="button" onClick={() => void installUpdate()}>Try again</button>
            <button className="link" onClick={() => set({ update: null })}>Dismiss</button>
          </span>
        </>
      )}
    </div>
  );
}
