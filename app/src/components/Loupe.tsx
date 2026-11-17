import { useEffect, useRef, useState } from "react";
import { api, imageUrl } from "../api";
import { useStore } from "../store";
import type { PhotoDetail } from "../types";

/** One photo, large. Z zooms to 100% of the preview, centred on the main face when there is one. */
export function Loupe() {
  const { photos, selectedId, zoomed } = useStore();
  const photo = photos.find((p) => p.id === selectedId);
  const [detail, setDetail] = useState<PhotoDetail | null>(null);
  const frame = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    setDetail(null);
    if (selectedId === null) return;
    let live = true;
    api.photo(selectedId).then((d) => live && setDetail(d)).catch(() => undefined);
    return () => {
      live = false;
    };
  }, [selectedId]);

  // Warm the cache for the neighbours so the next arrow press is instant.
  useEffect(() => {
    const list = useStore.getState().visible();
    const i = list.findIndex((p) => p.id === selectedId);
    for (const neighbour of [list[i + 1], list[i - 1], list[i + 2]]) {
      if (neighbour && neighbour.status === "done") new Image().src = imageUrl(neighbour, "preview");
    }
  }, [selectedId]);

  if (!photo) return <div className="empty"><p>Select a photo.</p></div>;
  if (photo.status === "error") {
    return <div className="empty"><p>{photo.name} could not be read. {photo.error}</p></div>;
  }

  const face = detail?.faces.find((f) => f.main);
  const origin = face ? `${(face.box_rel[0] + face.box_rel[2] / 2) * 100}% ${(face.box_rel[1] + face.box_rel[3] / 2) * 100}%` : "50% 50%";

  return (
    <div className={`loupe${zoomed ? " is-zoomed" : ""}`} ref={frame} onDoubleClick={() => useStore.getState().set({ zoomed: !zoomed })}>
      <img
        key={photo.id}
        src={imageUrl(photo, "preview")}
        alt={photo.name}
        draggable={false}
        onLoad={(e) => {
          const img = e.currentTarget;
          setScale(Math.max(1, img.naturalWidth / Math.max(1, img.clientWidth)));
        }}
        style={{ transformOrigin: origin, transform: zoomed ? `scale(${scale})` : "none" }}
      />
      <div className="loupe-caption">
        <span>{photo.name}</span>
        {photo.burst_size > 1 && <span>Frame {(photo.burst_rank ?? 0) + 1} of {photo.burst_size}</span>}
        {zoomed && <span>100%{face ? " on the main face" : ""}</span>}
      </div>
    </div>
  );
}
