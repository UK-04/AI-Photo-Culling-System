import { useMemo } from "react";
import { chooseAndOpenFolder } from "../actions";
import { countPhotos } from "../logic";
import { useStore } from "../store";
import type { Filter } from "../types";

const FILTERS: { id: Filter; name: string; dot?: string; count: (c: ReturnType<typeof countPhotos>) => number }[] = [
  { id: "all", name: "All photos", count: (c) => c.total },
  { id: "keep", name: "Keep", dot: "keep", count: (c) => c.keep },
  { id: "review", name: "Review", dot: "review", count: (c) => c.review },
  { id: "reject", name: "Reject", dot: "reject", count: (c) => c.reject },
  { id: "undecided", name: "Undecided", count: (c) => c.undecided - c.errors },
  { id: "picked", name: "Picked by you", count: (c) => c.picked },
  { id: "rated3", name: "3 stars and up", count: (c) => c.rated3 },
];

export function Sidebar() {
  const { shoots, shootId, photos, filter, selectShoot, setFilter, removeShoot } = useStore();
  const counts = useMemo(() => countPhotos(photos), [photos]);

  return (
    <aside className="sidebar">
      <div className="sidebar-drag" data-tauri-drag-region />
      <div className="sidebar-section">
        <div className="sidebar-heading">
          <span>Shoots</span>
          <button className="icon-button" title="Open a folder (⌘O)" aria-label="Open a folder" onClick={() => void chooseAndOpenFolder()}>
            +
          </button>
        </div>
        {shoots.length === 0 && <p className="sidebar-empty">No shoots yet.</p>}
        <ul className="list">
          {shoots.map((s) => (
            <li key={s.id}>
              <button className={`row${s.id === shootId ? " is-active" : ""}`} onClick={() => void selectShoot(s.id)} title={s.folder_path}>
                <span className="row-name">{s.name}</span>
                <span className="row-count">{s.id === shootId ? counts.total : s.counts.total}</span>
              </button>
              {s.id === shootId && (
                <button
                  className="row-remove"
                  title="Remove from Culler. Your photos stay where they are."
                  aria-label={`Remove ${s.name} from Culler`}
                  onClick={() => {
                    if (window.confirm(`Remove “${s.name}” from Culler?\n\nYour photos are not touched, and what Culler learned from this shoot is kept.`)) {
                      void removeShoot(s.id);
                    }
                  }}
                >
                  ×
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>

      {shootId !== null && (
        <div className="sidebar-section">
          <div className="sidebar-heading"><span>Show</span></div>
          <ul className="list">
            {FILTERS.map((f) => (
              <li key={f.id}>
                <button className={`row${filter === f.id ? " is-active" : ""}`} onClick={() => void setFilter(f.id)}>
                  {f.dot ? <span className={`dot dot-${f.dot}`} /> : <span className="dot dot-none" />}
                  <span className="row-name">{f.name}</span>
                  <span className="row-count">{Math.max(0, f.count(counts))}</span>
                </button>
              </li>
            ))}
            <li>
              <button
                className={`row${filter === "teach" ? " is-active" : ""}`}
                onClick={() => void setFilter("teach")}
                title="The photos Culler is least sure about. Deciding these teaches it the most."
              >
                <span className="dot dot-none" />
                <span className="row-name">Teach Culler</span>
              </button>
            </li>
          </ul>
        </div>
      )}
    </aside>
  );
}
