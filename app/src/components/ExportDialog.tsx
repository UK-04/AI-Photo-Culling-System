import { useMemo, useState } from "react";
import { api, pickFolder, type ExportReport, type ExportRequest } from "../api";
import { countPhotos } from "../logic";
import { useStore } from "../store";

type Kind = ExportRequest["kind"];
type Selection = ExportRequest["selection"];

const KINDS: { id: Kind; name: string; blurb: string }[] = [
  { id: "xmp", name: "Lightroom sidecars", blurb: "Writes a small .xmp file next to each RAW photo with its colour label and stars. Your photos are not changed." },
  { id: "folder", name: "Copy to a folder", blurb: "Copies the selected photos. JPEG copies carry the label and stars inside the file, so they show up in Lightroom." },
  { id: "csv", name: "Spreadsheet (CSV)", blurb: "One row per photo: decision, reason and scores." },
];

export function ExportDialog() {
  const { shootId, photos, set } = useStore();
  const counts = useMemo(() => countPhotos(photos), [photos]);
  const hasRaw = useMemo(() => photos.some((p) => /\.(cr3|cr2|nef|arw|raf|dng)$/i.test(p.name)), [photos]);
  const [kind, setKind] = useState<Kind>(hasRaw ? "xmp" : "folder");
  const [selection, setSelection] = useState<Selection>(kind === "folder" ? "keep" : "all");
  const [dest, setDest] = useState("");
  const [byCategory, setByCategory] = useState(false);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState<ExportReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selections: { id: Selection; name: string; n: number }[] = [
    { id: "picked", name: "Only photos I picked", n: counts.picked },
    { id: "keep", name: "My picks plus Culler's keeps", n: counts.keep },
    { id: "decided", name: "Everything I flagged or rated", n: photos.filter((p) => p.user_label || p.user_rating > 0).length },
    { id: "all", name: "All photos", n: counts.total - counts.errors },
  ];
  const needsDest = kind !== "xmp";

  async function run() {
    if (shootId === null) return;
    setBusy(true);
    setError(null);
    try {
      setReport(await api.exportShoot(shootId, { kind, selection, dest: needsDest ? dest : undefined, by_category: kind === "folder" && byCategory }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="scrim" onMouseDown={(e) => e.target === e.currentTarget && set({ dialog: null })}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="export-title">
        <h2 id="export-title">Export</h2>

        {report ? (
          <Result report={report} />
        ) : (
          <>
            <div className="choice-list">
              {KINDS.map((k) => (
                <label key={k.id} className={`choice${kind === k.id ? " is-on" : ""}`}>
                  <input type="radio" name="kind" checked={kind === k.id} onChange={() => { setKind(k.id); if (k.id === "folder") setSelection("keep"); }} />
                  <span>
                    <strong>{k.name}</strong>
                    <span className="muted">{k.blurb}</span>
                  </span>
                </label>
              ))}
            </div>

            {kind === "xmp" && (
              <p className="note">
                Lightroom stores pick and reject flags only in its own catalog, so no other app can set them. Culler writes colour labels
                instead: green for keep, yellow for review, red for reject. In Lightroom, filter by the red label and press X to flag them all.
                {!hasRaw && " This shoot has no RAW files, and Lightroom ignores sidecars for JPEGs: use Copy to a folder instead."}
              </p>
            )}

            <label className="field">
              <span>Which photos</span>
              <select value={selection} onChange={(e) => setSelection(e.target.value as Selection)}>
                {selections.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.n})</option>)}
              </select>
            </label>

            {needsDest && (
              <label className="field">
                <span>{kind === "folder" ? "Copy into" : "Save in"}</span>
                <span className="field-row">
                  <input type="text" value={dest} onChange={(e) => setDest(e.target.value)} placeholder="Choose a folder" spellCheck={false} />
                  <button className="button" onClick={async () => { const f = await pickFolder("Choose a destination folder"); if (f) setDest(f); }}>Choose…</button>
                </span>
              </label>
            )}
            {kind === "folder" && (
              <label className="check">
                <input type="checkbox" checked={byCategory} onChange={(e) => setByCategory(e.target.checked)} />
                Sort into a folder for each topic (Group photos, Details, …)
              </label>
            )}
            {error && <p className="error-text">{error}</p>}
          </>
        )}

        <div className="dialog-actions">
          <button className="button" onClick={() => set({ dialog: null })}>{report ? "Close" : "Cancel"}</button>
          {!report && (
            <button className="button button-primary" onClick={() => void run()} disabled={busy || (needsDest && !dest.trim())}>
              {busy ? "Exporting…" : "Export"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function Result({ report }: { report: ExportReport }) {
  const n = (key: string) => Number(report[key] ?? 0);
  const lines: string[] = [];
  if (report.kind === "xmp") {
    lines.push(`${n("written")} sidecar${n("written") === 1 ? "" : "s"} written (${n("created")} new, ${n("merged")} updated).`);
    if (n("skipped_not_raw")) lines.push(`${n("skipped_not_raw")} JPEG, HEIC or PNG photos skipped: Lightroom reads sidecars for RAW files only.`);
    if (n("skipped_missing")) lines.push(`${n("skipped_missing")} photos skipped because the original was not found.`);
  } else if (report.kind === "folder") {
    lines.push(`${n("copied")} photo${n("copied") === 1 ? "" : "s"} copied to ${String(report.dest)}.`);
    if (n("already_there")) lines.push(`${n("already_there")} were already there.`);
    const folders = report.folders as Record<string, number> | undefined;
    if (folders) lines.push(`Sorted into ${Object.keys(folders).length} folders: ${Object.entries(folders).map(([k, v]) => `${k} (${v})`).join(", ")}.`);
    if (n("ratings_embedded")) lines.push(`${n("ratings_embedded")} JPEG copies carry their label and stars.`);
    if (n("skipped_missing")) lines.push(`${n("skipped_missing")} skipped because the original was not found.`);
  } else {
    lines.push(`${n("rows")} rows saved to ${String(report.dest)}.`);
  }
  const failed = report.failed ?? [];
  return (
    <div className="result">
      {lines.map((l) => <p key={l}>{l}</p>)}
      {failed.length > 0 && (
        <>
          <p className="error-text">{failed.length} could not be written:</p>
          <ul>{failed.slice(0, 8).map((f) => <li key={f}>{f}</li>)}</ul>
        </>
      )}
    </div>
  );
}
