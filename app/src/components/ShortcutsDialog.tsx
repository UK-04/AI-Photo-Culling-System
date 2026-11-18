import { useStore } from "../store";

const SHORTCUTS: [string, string][] = [
  ["P", "Pick (keep)"],
  ["X", "Reject"],
  ["U", "Unflag"],
  ["1 – 5", "Star rating (0 clears)"],
  ["← →  ↑ ↓", "Move between photos"],
  ["Space", "Switch between grid and loupe"],
  ["Z or click", "Zoom in and out. Drag to move around"],
  ["+  −", "Change how far Z and click zoom in"],
  ["[  ]", "Rotate left, right"],
  ["C", "Compare the frames of a burst"],
  ["S", "Open or close a burst stack"],
  ["Tab", "Next photo that needs a decision"],
  ["I", "Show or hide the inspector"],
  ["⌘Z  ⇧⌘Z", "Undo, redo"],
  ["⌘O", "Open a folder"],
  ["⇧⌘O", "Select photos"],
  ["⌘E", "Export"],
];

export function ShortcutsDialog() {
  const { set, autoAdvance } = useStore();
  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && set({ dialog: null })}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="keys-title">
        <h2 id="keys-title">Keyboard shortcuts</h2>
        <dl className="shortcuts">
          {SHORTCUTS.map(([keys, what]) => (
            <div key={keys}>
              <dt><kbd>{keys}</kbd></dt>
              <dd>{what}</dd>
            </div>
          ))}
        </dl>
        <label className="check">
          <input
            type="checkbox"
            checked={autoAdvance}
            onChange={(e) => {
              localStorage.setItem("culler-auto-advance", e.target.checked ? "on" : "off");
              set({ autoAdvance: e.target.checked });
            }}
          />
          Move to the next photo after picking or rejecting
        </label>
        <div className="dialog-actions">
          <button className="button button-primary" onClick={() => set({ dialog: null })}>Done</button>
        </div>
      </div>
    </div>
  );
}
