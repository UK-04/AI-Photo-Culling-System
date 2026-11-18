import { chooseAndOpenFolder, chooseAndOpenPhotos } from "../actions";
import { useStore } from "../store";

export function Welcome() {
  const set = useStore((s) => s.set);
  return (
    <div className="welcome" data-tauri-drag-region>
      <div className="welcome-inner">
        <h1>Cull a shoot in minutes</h1>
        <ol>
          <li><strong>Open a folder.</strong> Photos stay where they are. Nothing is uploaded, moved or deleted.</li>
          <li><strong>Review with the keyboard.</strong> Culler flags blur, closed eyes and blown faces, stacks bursts, and says why. P picks, X rejects.</li>
          <li><strong>Export to Lightroom.</strong> Every decision you make teaches Culler your taste for the next shoot.</li>
        </ol>
        <div className="welcome-actions">
          <button className="button button-primary button-large" onClick={() => void chooseAndOpenFolder()}>Open a folder…</button>
          <button className="button button-large" onClick={() => void chooseAndOpenPhotos()}>Select photos…</button>
          <button className="link" onClick={() => set({ dialog: "shortcuts" })}>Keyboard shortcuts</button>
        </div>
        <p className="muted small">Reads JPG, HEIC, PNG and RAW (CR3, CR2, NEF, ARW, RAF, DNG).</p>
      </div>
    </div>
  );
}
