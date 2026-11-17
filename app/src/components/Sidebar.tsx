import { useMemo } from "react";
import { chooseAndOpenFolder, chooseAndOpenPhotos } from "../actions";
import { categoryCounts, countPhotos } from "../logic";
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
const fixableCount = (photos: { recover_score: number | null }[]) =>
  photos.filter((p) => p.recover_score !== null && p.recover_score >= 0.5 && p.recover_score < 1).length;

export function Sidebar() {
  const { shoots, shootId, photos, filter, selectShoot, setFilter, removeShoot, category, setCategory, shootTypes, setShootType } = useStore();
  const counts = useMemo(() => countPhotos(photos), [photos]);
  const topics = useMemo(() => categoryCounts(photos), [photos]);
  const offTopic = useMemo(() => photos.filter((p) => p.off_topic).length, [photos]);
  const shoot = shoots.find((s) => s.id === shootId);

  return (
    <aside className="sidebar">
      <div className="sidebar-drag" data-tauri-drag-region />
      <div className="sidebar-section">
        <div className="sidebar-heading">
          <span>Shoots</span>
          <span className="sidebar-add">
            <button className="link small" title="Open a folder (⌘O)" onClick={() => void chooseAndOpenFolder()}>Folder…</button>
            <button className="link small" title="Select individual photos (⇧⌘O)" onClick={() => void chooseAndOpenPhotos()}>Photos…</button>
          </span>
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
                className={`row${filter === "fixable" ? " is-active" : ""}`}
                onClick={() => void setFilter("fixable")}
                title="Photos with a problem that editing can fix, such as exposure"
              >
                <span className="dot dot-none" />
                <span className="row-name">Fixable in editing</span>
                <span className="row-count">{fixableCount(photos)}</span>
              </button>
            </li>
            <li>
              <button
                className={`row${filter === "offtopic" ? " is-active" : ""}`}
                onClick={() => void setFilter("offtopic")}
                title="Photos unlike the rest of this shoot"
              >
                <span className="dot dot-none" />
                <span className="row-name">Off-topic</span>
                <span className="row-count">{offTopic}</span>
              </button>
            </li>
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
      {shootId !== null && topics.length > 0 && (
        <div className="sidebar-section">
          <div className="sidebar-heading">
            <span>Topics</span>
            <select
              className="sidebar-select"
              value={shoot?.shoot_type ?? "general"}
              onChange={(e) => { void setShootType(e.target.value); e.currentTarget.blur(); }}
              onKeyDown={(e) => e.stopPropagation()}
              title="What kind of shoot this is. It decides the topics photos are sorted into."
              aria-label="Kind of shoot"
            >
              {shootTypes.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
          <ul className="list">
            <li>
              <button className={`row${category === null ? " is-active" : ""}`} onClick={() => setCategory(null)}>
                <span className="dot dot-none" />
                <span className="row-name">All topics</span>
              </button>
            </li>
            {topics.map((t) => (
              <li key={t.name}>
                <button className={`row${category === t.name ? " is-active" : ""}`} onClick={() => setCategory(category === t.name ? null : t.name)}>
                  <span className="dot dot-none" />
                  <span className="row-name">{t.name}</span>
                  <span className="row-count">{t.count}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </aside>
  );
}
