import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, imageUrl } from "../api";
import { ZOOM_LEVELS, clampPan, scaleForLevel } from "../logic";
import { useStore } from "../store";
import type { PhotoDetail } from "../types";

/**
 * One photo, large. Works like Lightroom's loupe:
 *  - click (or Z) zooms to the chosen level at the point you clicked, click again zooms out
 *  - drag, or scroll, to move around while zoomed
 *  - pinch (or ⌘-scroll) zooms freely
 *  - moving to the next photo keeps the zoom and position, to compare focus across frames
 *
 * Zooming is a GPU transform applied straight to the element, so it responds on the same
 * frame. The screen-size preview is shown at once and the full-resolution file is swapped
 * in underneath as soon as it has loaded.
 */
const ZOOM_EASE = "transform 220ms cubic-bezier(0.22, 0.8, 0.24, 1)";

export function Loupe() {
  const { photos, selectedId, zoomed, zoomLevel, setZoomLevel } = useStore();
  const photo = photos.find((p) => p.id === selectedId);
  const [detail, setDetail] = useState<PhotoDetail | null>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const [fullFor, setFullFor] = useState<string | null>(null); // key of the photo whose full-size file is loaded
  const [dragging, setDragging] = useState(false);

  const viewEl = useRef<HTMLDivElement>(null);
  const imageEl = useRef<HTMLDivElement>(null);
  // Live geometry. Kept out of React state so panning never waits for a render.
  const g = useRef({ scale: 1, x: 0, y: 0, fitW: 0, fitH: 0, fit: 1, cx: 0.5, cy: 0.5 });
  const anchor = useRef<{ x: number; y: number } | null>(null); // where the click landed
  const freeZoom = useRef(false); // true while the scale comes from a pinch, not a level
  const last = useRef({ zoomed: false, level: "", key: "" });
  const press = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const laidOut = useRef(false); // no animation on the very first layout
  const [shownPercent, setShownPercent] = useState(100);

  const iw = photo?.width || 3;
  const ih = photo?.height || 2;
  const key = photo ? `${photo.id}-${photo.rotation}` : "";

  function apply(animate = false) {
    const s = g.current;
    // A click or key press eases to the new zoom. Anything driven by the hand (drag, scroll,
    // pinch) must track it exactly, so those never animate.
    if (imageEl.current) imageEl.current.style.transition = animate ? ZOOM_EASE : "none";
    s.x = clampPan(s.x, s.fitW * s.scale, box.w);
    s.y = clampPan(s.y, s.fitH * s.scale, box.h);
    s.cx = (box.w / 2 - s.x) / (s.fitW * s.scale);
    s.cy = (box.h / 2 - s.y) / (s.fitH * s.scale);
    if (imageEl.current) imageEl.current.style.transform = `translate3d(${s.x}px, ${s.y}px, 0) scale(${s.scale})`;
    const pct = Math.round(s.scale * s.fit * 100);
    setShownPercent((old) => (old === pct ? old : pct));
  }

  /** Scale to `scale`, keeping the image point under (px, py) where it is. */
  function zoomAt(px: number, py: number, scale: number) {
    const s = g.current;
    const u = (px - s.x) / s.scale;
    const v = (py - s.y) / s.scale;
    s.scale = scale;
    s.x = px - u * scale;
    s.y = py - v * scale;
    apply();
  }

  useEffect(() => {
    setDetail(null);
    if (selectedId === null) return;
    let live = true;
    api.photo(selectedId).then((d) => live && setDetail(d)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [selectedId, photo?.rotation]);

  useLayoutEffect(() => {
    const el = viewEl.current;
    if (!el) return;
    const measure = () => setBox({ w: el.clientWidth, h: el.clientHeight });
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    measure();
    return () => observer.disconnect();
  }, [photo?.status]);

  // Lay the image out and set the zoom whenever the photo, the box, or the zoom setting changes.
  useLayoutEffect(() => {
    if (!box.w || !box.h || !photo) return;
    const s = g.current;
    s.fit = Math.min(box.w / iw, box.h / ih);
    s.fitW = iw * s.fit;
    s.fitH = ih * s.fit;
    if (imageEl.current) {
      imageEl.current.style.width = `${s.fitW}px`;
      imageEl.current.style.height = `${s.fitH}px`;
    }
    const target = scaleForLevel(zoomLevel, s.fit, s.fitW, s.fitH, box.w, box.h);
    const toggled = last.current.zoomed !== zoomed || last.current.level !== zoomLevel;
    const changedPhoto = last.current.key !== key;
    last.current = { zoomed, level: zoomLevel, key };

    if (!zoomed) {
      freeZoom.current = false;
      s.scale = 1;
      s.x = (box.w - s.fitW) / 2;
      s.y = (box.h - s.fitH) / 2;
    } else if (toggled && !freeZoom.current) {
      // Zoom in on the click, else the main face, else the middle.
      const face = detail?.id === photo.id ? detail.faces.find((f) => f.main) : undefined;
      const at = anchor.current;
      if (at && s.scale === 1) {
        const u = (at.x - s.x) / s.fitW;
        const v = (at.y - s.y) / s.fitH;
        s.cx = Math.min(1, Math.max(0, u));
        s.cy = Math.min(1, Math.max(0, v));
      } else if (!at && s.scale === 1) {
        s.cx = face ? face.box_rel[0] + face.box_rel[2] / 2 : 0.5;
        s.cy = face ? face.box_rel[1] + face.box_rel[3] / 2 : 0.5;
      }
      s.scale = target;
      s.x = box.w / 2 - s.cx * s.fitW * s.scale;
      s.y = box.h / 2 - s.cy * s.fitH * s.scale;
    } else {
      // Same zoom, new photo or new window size: stay on the same spot.
      if (changedPhoto && !freeZoom.current) s.scale = target;
      s.x = box.w / 2 - s.cx * s.fitW * s.scale;
      s.y = box.h / 2 - s.cy * s.fitH * s.scale;
    }
    anchor.current = null;
    apply(toggled && !changedPhoto && laidOut.current);
    laidOut.current = true;
  }, [box.w, box.h, key, iw, ih, zoomed, zoomLevel]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch the full-resolution file once the photographer zooms in, after a short pause
  // so that arrowing quickly through photos does not load every one.
  useEffect(() => {
    if (!zoomed || !photo || photo.status !== "done" || fullFor === key) return;
    let live = true;
    const timer = setTimeout(() => {
      const img = new Image();
      img.onload = () => live && setFullFor(key);
      img.src = imageUrl(photo, "full");
    }, 120);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [zoomed, key]); // eslint-disable-line react-hooks/exhaustive-deps

  // Warm the cache for the neighbours so the next arrow press is instant.
  useEffect(() => {
    const list = useStore.getState().visible();
    const i = list.findIndex((p) => p.id === selectedId);
    for (const neighbour of [list[i + 1], list[i - 1], list[i + 2]]) {
      if (neighbour && neighbour.status === "done") new Image().src = imageUrl(neighbour, "preview");
    }
  }, [selectedId]);

  // Scroll to move, pinch or ⌘-scroll to zoom. Needs a non-passive listener to stop page zoom.
  useEffect(() => {
    const el = viewEl.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const s = g.current;
      const rect = el.getBoundingClientRect();
      if (e.ctrlKey || e.metaKey) {
        const next = Math.min(8 / s.fit, Math.max(1, s.scale * Math.exp(-e.deltaY * 0.01)));
        const isZoomed = next > 1.001;
        freeZoom.current = isZoomed;
        zoomAt(e.clientX - rect.left, e.clientY - rect.top, isZoomed ? next : 1);
        if (useStore.getState().zoomed !== isZoomed) {
          last.current.zoomed = isZoomed; // the layout effect must not re-centre a pinch
          useStore.getState().set({ zoomed: isZoomed });
        }
      } else if (s.scale > 1.001) {
        s.x -= e.deltaX;
        s.y -= e.deltaY;
        apply();
      }
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [box.w, box.h, photo?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!photo) return <div className="empty"><p>Select a photo.</p></div>;
  if (photo.status === "error") {
    return <div className="empty"><p>{photo.name} could not be read. {photo.error}</p></div>;
  }

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    press.current = { x: e.clientX, y: e.clientY, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const p = press.current;
    if (!p) return;
    if (!p.moved && Math.hypot(e.clientX - p.x, e.clientY - p.y) < 4) return;
    if (g.current.scale <= 1.001) return; // nothing to drag when the whole photo is in view
    if (!p.moved) setDragging(true);
    p.moved = true;
    g.current.x += e.movementX;
    g.current.y += e.movementY;
    apply();
  };
  const onPointerUp = (e: React.PointerEvent) => {
    const p = press.current;
    press.current = null;
    setDragging(false);
    if (!p || p.moved) return;
    const rect = e.currentTarget.getBoundingClientRect();
    anchor.current = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    freeZoom.current = false;
    useStore.getState().set({ zoomed: !useStore.getState().zoomed });
  };

  return (
    <div className="loupe">
      <div
        ref={viewEl}
        className={`loupe-view${zoomed ? " is-zoomed" : ""}${dragging ? " is-dragging" : ""}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => { press.current = null; setDragging(false); }}
      >
        <div className="loupe-image" ref={imageEl}>
          <img key={`p-${key}`} className="loupe-arrive" src={imageUrl(photo, "preview")} alt={photo.name} draggable={false} />
          {fullFor === key && <img key={`f-${key}`} src={imageUrl(photo, "full")} alt="" draggable={false} decoding="async" />}
        </div>
      </div>
      <div className="loupe-caption">
        <span>{photo.name}</span>
        {photo.burst_size > 1 && <span>Photo {(photo.burst_rank ?? 0) + 1} of {photo.burst_size} in its group</span>}
        <label>
          Click zooms to{" "}
          <select value={zoomLevel} onChange={(e) => { setZoomLevel(e.target.value); e.currentTarget.blur(); }} onKeyDown={(e) => e.stopPropagation()}>
            {ZOOM_LEVELS.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        </label>
        {zoomed && <span>{shownPercent}%{fullFor === key ? "" : ", loading full size…"}</span>}
      </div>
    </div>
  );
}
