import { useStore } from "../store";
import type { Sort, View } from "../types";

const VIEWS: { id: View; name: string; hint: string }[] = [
  { id: "grid", name: "Grid", hint: "Space" },
  { id: "loupe", name: "Loupe", hint: "Space" },
  { id: "compare", name: "Compare", hint: "C" },
];

export function Toolbar() {
  const { shoots, shootId, view, sort, setView, setSort, inspectorOpen, set, rescan, progress, finishShoot } = useStore();
  const shoot = shoots.find((s) => s.id === shootId);
  const scanning = progress?.running ?? false;

  return (
    <header className="toolbar" data-tauri-drag-region>
      <h1 className="toolbar-title" data-tauri-drag-region>{shoot?.name ?? ""}</h1>

      <div className="segmented" role="group" aria-label="View">
        {VIEWS.map((v) => (
          <button key={v.id} className={view === v.id ? "is-on" : ""} onClick={() => setView(v.id)} title={`${v.name} (${v.hint})`}>
            {v.name}
          </button>
        ))}
      </div>

      <label className="select">
        <span>Sort</span>
        <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
          <option value="time">Capture time</option>
          <option value="score">Score</option>
          <option value="sharpness">Sharpness</option>
        </select>
      </label>

      <div className="toolbar-spacer" data-tauri-drag-region />

      <button className="button" onClick={() => void rescan()} disabled={scanning} title="Look for new or changed photos in this folder">
        Rescan
      </button>
      <button className="button" onClick={() => void finishShoot()} disabled={scanning} title="Tell Culler you are finished so it can learn from this shoot">
        Done culling
      </button>
      <button className="button button-primary" onClick={() => set({ dialog: "export" })} disabled={scanning} title="Export (⌘E)">
        Export…
      </button>
      <button
        className={`icon-button${inspectorOpen ? " is-on" : ""}`}
        onClick={() => set({ inspectorOpen: !inspectorOpen })}
        title="Show or hide the inspector (I)"
        aria-label="Toggle inspector"
        aria-pressed={inspectorOpen}
      >
        ⓘ
      </button>
    </header>
  );
}
