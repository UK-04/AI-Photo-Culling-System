import { useEffect } from "react";
import { chooseAndOpenFolder } from "./actions";
import { isTauri } from "./api";
import { BottomBar } from "./components/BottomBar";
import { Compare } from "./components/Compare";
import { ExportDialog } from "./components/ExportDialog";
import { Grid } from "./components/Grid";
import { Inspector } from "./components/Inspector";
import { Loupe } from "./components/Loupe";
import { ShortcutsDialog } from "./components/ShortcutsDialog";
import { Sidebar } from "./components/Sidebar";
import { Toolbar } from "./components/Toolbar";
import { Welcome } from "./components/Welcome";
import { useStore } from "./store";

function useKeyboard() {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const s = useStore.getState();
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT")) return;
      const mod = e.metaKey || e.ctrlKey;

      if (s.dialog) {
        if (e.key === "Escape") s.set({ dialog: null });
        return;
      }
      if (mod) {
        const key = e.key.toLowerCase();
        if (key === "z") {
          e.preventDefault();
          if (e.shiftKey) s.redo();
          else s.undo();
        } else if (key === "e") {
          e.preventDefault();
          if (s.shootId !== null) s.set({ dialog: "export" });
        } else if (key === "o") {
          e.preventDefault();
          void chooseAndOpenFolder();
        }
        return;
      }
      if (e.altKey) return;

      switch (e.key) {
        case "p": case "P": s.decide({ label: "KEEP" }); break;
        case "x": case "X": s.decide({ label: "REJECT" }); break;
        case "u": case "U": s.decide({ label: null }); break;
        case "0": case "1": case "2": case "3": case "4": case "5":
          s.decide({ rating: Number(e.key) });
          break;
        case "ArrowRight": s.move(1); break;
        case "ArrowLeft": s.move(-1); break;
        case "ArrowDown": s.move(s.view === "grid" ? s.columns : 1); break;
        case "ArrowUp": s.move(s.view === "grid" ? -s.columns : -1); break;
        case " ": s.setView(s.view === "grid" ? "loupe" : "grid"); break;
        case "Enter": if (s.view === "grid") s.setView("loupe"); break;
        case "Escape": if (s.view !== "grid") s.setView("grid"); break;
        case "z": case "Z":
          if (s.view !== "loupe") s.set({ view: "loupe", zoomed: true });
          else s.set({ zoomed: !s.zoomed });
          break;
        case "c": case "C": s.setView(s.view === "compare" ? "grid" : "compare"); break;
        case "s": case "S": s.toggleBurst(); break;
        case "i": case "I": s.set({ inspectorOpen: !s.inspectorOpen }); break;
        case "Tab": s.jumpToNextReview(); break;
        case "?": s.set({ dialog: "shortcuts" }); break;
        default: return;
      }
      e.preventDefault();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** Native menu items (File > Open Folder, Edit > Undo, ...) arrive as events from the shell. */
function useNativeMenu() {
  useEffect(() => {
    if (!isTauri) return;
    let unlisten: (() => void) | undefined;
    void import("@tauri-apps/api/event").then(async ({ listen }) => {
      unlisten = await listen<string>("menu", (event) => {
        const s = useStore.getState();
        switch (event.payload) {
          case "open_folder": void chooseAndOpenFolder(); break;
          case "export": if (s.shootId !== null) s.set({ dialog: "export" }); break;
          case "undo": s.undo(); break;
          case "redo": s.redo(); break;
          case "rescan": void s.rescan(); break;
          case "shortcuts": s.set({ dialog: "shortcuts" }); break;
          case "toggle_inspector": s.set({ inspectorOpen: !s.inspectorOpen }); break;
        }
      });
    });
    return () => unlisten?.();
  }, []);
}

export function App() {
  const { connected, fatal, shootId, view, inspectorOpen, dialog, toast } = useStore();
  useEffect(() => {
    void useStore.getState().init();
  }, []);
  useKeyboard();
  useNativeMenu();

  if (fatal) {
    return (
      <div className="splash">
        <h1>Culler could not start</h1>
        <p>{fatal}</p>
      </div>
    );
  }
  if (!connected) {
    return (
      <div className="splash">
        <div className="spinner" aria-hidden />
        <p>Starting the analysis engine…</p>
      </div>
    );
  }

  return (
    <div className={`app${isTauri ? " in-shell" : ""}`}>
      <Sidebar />
      <main className="main">
        {shootId === null ? (
          <Welcome />
        ) : (
          <>
            <Toolbar />
            <div className="stage">
              <div className="canvas">
                {view === "grid" && <Grid />}
                {view === "loupe" && <Loupe />}
                {view === "compare" && <Compare />}
              </div>
              {inspectorOpen && <Inspector />}
            </div>
            <BottomBar />
          </>
        )}
      </main>
      {dialog === "export" && <ExportDialog />}
      {dialog === "shortcuts" && <ShortcutsDialog />}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
