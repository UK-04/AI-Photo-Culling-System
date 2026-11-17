import { useVirtualizer } from "@tanstack/react-virtual";
import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { imageUrl } from "../api";
import { effectiveLabel, visiblePhotos } from "../logic";
import { useStore } from "../store";
import type { Photo } from "../types";

const CELL = 196; // target cell width in px
const GAP = 10;

export function Grid() {
  const { photos, filter, sort, expanded, teachIds, selectedId, progress } = useStore();
  const list = useMemo(() => visiblePhotos(photos, filter, sort, expanded, teachIds), [photos, filter, sort, expanded, teachIds]);
  const scroller = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setWidth(el.clientWidth));
    observer.observe(el);
    setWidth(el.clientWidth);
    return () => observer.disconnect();
  }, []);

  const columns = Math.max(2, Math.floor((width - GAP) / (CELL + GAP)) || 2);
  const cell = Math.floor((width - GAP * (columns + 1)) / columns);
  const rowHeight = Math.round(cell * 0.75) + 30 + GAP;
  const rows = Math.ceil(list.length / columns);

  useEffect(() => {
    useStore.getState().set({ columns });
  }, [columns]);

  const virtual = useVirtualizer({ count: rows, getScrollElement: () => scroller.current, estimateSize: () => rowHeight, overscan: 4 });
  useEffect(() => virtual.measure(), [rowHeight]); // eslint-disable-line react-hooks/exhaustive-deps

  // Keep the selected cell on screen when moving with the keyboard.
  const selectedIndex = list.findIndex((p) => p.id === selectedId);
  useEffect(() => {
    if (selectedIndex >= 0) virtual.scrollToIndex(Math.floor(selectedIndex / columns), { align: "auto" });
  }, [selectedIndex, columns]); // eslint-disable-line react-hooks/exhaustive-deps

  if (list.length === 0) {
    return (
      <div className="empty" ref={scroller}>
        {progress?.running ? (
          <p>Thumbnails appear here as photos are analyzed.</p>
        ) : photos.length === 0 ? (
          <p>No supported photos in this folder. Culler reads JPG, HEIC, PNG and RAW (CR3, CR2, NEF, ARW, RAF, DNG).</p>
        ) : (
          <p>No photos match this view.</p>
        )}
      </div>
    );
  }

  return (
    <div className="grid-scroller" ref={scroller} tabIndex={-1}>
      <div style={{ height: virtual.getTotalSize(), position: "relative" }}>
        {width > 0 &&
          virtual.getVirtualItems().map((row) => (
            <div
              key={row.key}
              className="grid-row"
              style={{ transform: `translateY(${row.start}px)`, height: rowHeight, gap: GAP, padding: `0 ${GAP}px` }}
            >
              {list.slice(row.index * columns, (row.index + 1) * columns).map((p) => (
                <Cell key={p.id} photo={p} size={cell} selected={p.id === selectedId} stacked={p.burst_id !== null && !expanded.has(p.burst_id)} />
              ))}
            </div>
          ))}
      </div>
    </div>
  );
}

const Cell = memo(function Cell({ photo, size, selected, stacked }: { photo: Photo; size: number; selected: boolean; stacked: boolean }) {
  const label = effectiveLabel(photo);
  const decided = photo.user_label !== null;
  const classes = ["cell", selected && "is-selected", label === "REJECT" && "is-rejected", stacked && photo.burst_size > 1 && "is-stack"]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      className={classes}
      style={{ width: size }}
      onClick={() => useStore.getState().select(photo.id)}
      onDoubleClick={() => useStore.getState().setView("loupe")}
      aria-label={`${photo.name}, ${label ?? "not analyzed"}${photo.reason_primary ? `, ${photo.reason_primary}` : ""}`}
      aria-pressed={selected}
    >
      <span className="cell-frame" style={{ height: Math.round(size * 0.75) }}>
        {photo.status === "error" ? (
          <span className="cell-error">Unreadable</span>
        ) : (
          <img src={imageUrl(photo, "thumb")} alt="" loading="lazy" decoding="async" draggable={false} />
        )}
        {photo.burst_size > 1 && (
          <span className="badge badge-burst" title={stacked ? `Burst of ${photo.burst_size}. Press S to open.` : `Frame ${(photo.burst_rank ?? 0) + 1} of ${photo.burst_size}`}>
            {stacked ? photo.burst_size : `${(photo.burst_rank ?? 0) + 1}/${photo.burst_size}`}
          </span>
        )}
        {decided && <span className={`badge badge-flag flag-${photo.user_label === "KEEP" ? "keep" : "reject"}`}>{photo.user_label === "KEEP" ? "✓" : "✕"}</span>}
      </span>
      <span className="cell-meta">
        {label && <span className={`dot dot-${label.toLowerCase()}${decided ? "" : " is-suggested"}`} />}
        <span className="cell-reason">{photo.status === "error" ? "Could not read file" : photo.reason_primary ?? photo.name}</span>
        {photo.user_rating > 0 && <span className="stars">{"★".repeat(photo.user_rating)}</span>}
      </span>
    </button>
  );
});
