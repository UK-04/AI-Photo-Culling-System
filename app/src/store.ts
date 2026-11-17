import { create } from "zustand";
import { api } from "./api";
import { burstFrames, nextNeedingReview, visiblePhotos } from "./logic";
import type { Filter, ModelStatus, Photo, Progress, Shoot, Sort, UserLabel, View } from "./types";

interface Change {
  id: number;
  before: { label: UserLabel; rating: number };
  after: { label: UserLabel; rating: number };
}

interface State {
  connected: boolean;
  fatal: string | null;
  shoots: Shoot[];
  shootId: number | null;
  photos: Photo[];
  progress: Progress | null;
  filter: Filter;
  sort: Sort;
  view: View;
  selectedId: number | null;
  expanded: Set<number>;
  teachIds: Set<number>;
  inspectorOpen: boolean;
  zoomed: boolean;
  autoAdvance: boolean;
  columns: number;
  dialog: null | "export" | "shortcuts";
  toast: string | null;
  model: ModelStatus | null;
  undoStack: Change[][];
  redoStack: Change[][];

  init(): Promise<void>;
  refreshShoots(): Promise<void>;
  openFolder(path: string): Promise<void>;
  selectShoot(id: number): Promise<void>;
  removeShoot(id: number): Promise<void>;
  rescan(): Promise<void>;
  cancelScan(): Promise<void>;
  loadPhotos(): Promise<void>;
  setFilter(f: Filter): Promise<void>;
  setSort(s: Sort): void;
  setView(v: View): void;
  select(id: number | null): void;
  move(delta: number): void;
  toggleBurst(): void;
  jumpToNextReview(): void;
  decide(change: { label?: UserLabel; rating?: number }, reason?: string): void;
  undo(): void;
  redo(): void;
  finishShoot(): Promise<void>;
  refreshModel(): Promise<void>;
  set(partial: Partial<State>): void;
  notify(message: string): void;
  visible(): Photo[];
}

let stopWatching: (() => void) | null = null;
let toastTimer: ReturnType<typeof setTimeout> | undefined;
let refillTimer: ReturnType<typeof setInterval> | undefined;

export const useStore = create<State>((set, get) => ({
  connected: false,
  fatal: null,
  shoots: [],
  shootId: null,
  photos: [],
  progress: null,
  filter: "all",
  sort: "time",
  view: "grid",
  selectedId: null,
  expanded: new Set(),
  teachIds: new Set(),
  inspectorOpen: true,
  zoomed: false,
  autoAdvance: localStorage.getItem("culler-auto-advance") !== "off",
  columns: 5,
  dialog: null,
  toast: null,
  model: null,
  undoStack: [],
  redoStack: [],

  set: (partial) => set(partial),

  notify(message) {
    clearTimeout(toastTimer);
    set({ toast: message });
    toastTimer = setTimeout(() => set({ toast: null }), 4000);
  },

  visible() {
    const s = get();
    return visiblePhotos(s.photos, s.filter, s.sort, s.expanded, s.teachIds);
  },

  async init() {
    try {
      await api.ready();
      set({ connected: true });
      await get().refreshShoots();
      void get().refreshModel();
      const last = Number(localStorage.getItem("culler-last-shoot"));
      const shoots = get().shoots;
      const pick = shoots.find((s) => s.id === last) ?? shoots[0];
      if (pick) await get().selectShoot(pick.id);
    } catch (err) {
      set({ fatal: (err as Error).message });
    }
  },

  async refreshShoots() {
    set({ shoots: await api.shoots() });
  },

  async openFolder(path) {
    try {
      const shoot = await api.addShoot(path);
      await get().refreshShoots();
      await get().selectShoot(shoot.id);
      if (shoot.status !== "ready") await get().rescan();
    } catch (err) {
      get().notify((err as Error).message);
    }
  },

  async selectShoot(id) {
    stopWatching?.();
    clearInterval(refillTimer);
    localStorage.setItem("culler-last-shoot", String(id));
    set({
      shootId: id, photos: [], selectedId: null, filter: "all", view: "grid", expanded: new Set(),
      teachIds: new Set(), undoStack: [], redoStack: [], progress: null,
    });
    await get().loadPhotos();
    const first = get().visible()[0];
    if (first) set({ selectedId: first.id });

    await watch(id);
  },

  async removeShoot(id) {
    await api.removeShoot(id);
    if (get().shootId === id) {
      stopWatching?.();
      set({ shootId: null, photos: [], progress: null, selectedId: null });
    }
    await get().refreshShoots();
  },

  async rescan() {
    const id = get().shootId;
    if (id === null) return;
    set({ progress: await api.scan(id) });
    await watch(id);
  },

  async cancelScan() {
    const id = get().shootId;
    if (id !== null) await api.cancel(id);
  },

  async loadPhotos() {
    const id = get().shootId;
    if (id === null) return;
    try {
      const { photos } = await api.photos(id);
      if (get().shootId !== id) return;
      set({ photos });
      if (get().selectedId === null && photos.length) set({ selectedId: get().visible()[0]?.id ?? null });
    } catch (err) {
      get().notify((err as Error).message);
    }
  },

  async setFilter(filter) {
    const id = get().shootId;
    if (filter === "teach" && id !== null) {
      const { photo_ids } = await api.teach(id);
      set({ teachIds: new Set(photo_ids) });
    }
    set({ filter });
    const list = get().visible();
    if (!list.some((p) => p.id === get().selectedId)) set({ selectedId: list[0]?.id ?? null });
  },

  setSort(sort) {
    set({ sort });
  },

  setView(view) {
    if (view === "compare") {
      const s = get();
      const current = s.photos.find((p) => p.id === s.selectedId);
      if (!current || burstFrames(s.photos, current.burst_id).length < 2) {
        get().notify("Compare works on bursts. Select a photo that is part of a burst.");
        return;
      }
      // open the stack so the arrow keys walk through its frames
      set({ expanded: new Set(s.expanded).add(current.burst_id!) });
    }
    set({ view, zoomed: false });
  },

  select(id) {
    set({ selectedId: id, zoomed: false });
  },

  move(delta) {
    const list = get().visible();
    if (!list.length) return;
    const index = list.findIndex((p) => p.id === get().selectedId);
    const next = Math.min(list.length - 1, Math.max(0, (index < 0 ? 0 : index) + delta));
    set({ selectedId: list[next].id, zoomed: false });
  },

  toggleBurst() {
    const s = get();
    const current = s.photos.find((p) => p.id === s.selectedId);
    if (!current || current.burst_id === null) return;
    const expanded = new Set(s.expanded);
    if (expanded.has(current.burst_id)) {
      expanded.delete(current.burst_id);
      set({ expanded });
      // keep the selection on a cell that is still shown
      const list = get().visible();
      if (!list.some((p) => p.id === current.id)) {
        set({ selectedId: list.find((p) => p.burst_id === current.burst_id)?.id ?? list[0]?.id ?? null });
      }
    } else {
      expanded.add(current.burst_id);
      set({ expanded });
    }
  },

  jumpToNextReview() {
    const list = get().visible();
    const from = list.findIndex((p) => p.id === get().selectedId);
    const next = nextNeedingReview(list, Math.max(0, from));
    if (next >= 0) set({ selectedId: list[next].id, zoomed: false });
    else get().notify("Nothing left to review in this view.");
  },

  decide(change, reason) {
    const s = get();
    const target = s.photos.find((p) => p.id === s.selectedId);
    if (!target || target.status !== "done") return;
    const before = { label: target.user_label, rating: target.user_rating };
    const after = {
      label: change.label === undefined ? before.label : change.label,
      rating: change.rating === undefined ? before.rating : change.rating,
    };
    if (after.label === before.label && after.rating === before.rating) return;

    // Where to go next is worked out before the list changes under us.
    const list = s.visible();
    const index = list.findIndex((p) => p.id === target.id);
    const nextId = list[index + 1]?.id ?? null;

    apply(set, get, [{ id: target.id, before, after }], "after", reason);
    set({ undoStack: [...get().undoStack, [{ id: target.id, before, after }]].slice(-200), redoStack: [] });

    if (change.label !== undefined && change.label !== null && s.autoAdvance && s.view !== "compare" && nextId !== null) {
      set({ selectedId: nextId, zoomed: false });
    } else if (!get().visible().some((p) => p.id === target.id)) {
      // the photo left the current filter: move on rather than lose the selection
      set({ selectedId: nextId ?? get().visible()[0]?.id ?? null });
    }
  },

  undo() {
    const stack = get().undoStack;
    const last = stack[stack.length - 1];
    if (!last) return;
    apply(set, get, last, "before");
    set({ undoStack: stack.slice(0, -1), redoStack: [...get().redoStack, last], selectedId: last[0].id });
  },

  redo() {
    const stack = get().redoStack;
    const last = stack[stack.length - 1];
    if (!last) return;
    apply(set, get, last, "after");
    set({ redoStack: stack.slice(0, -1), undoStack: [...get().undoStack, last], selectedId: last[0].id });
  },

  async finishShoot() {
    const id = get().shootId;
    if (id === null) return;
    await api.finish(id);
    get().notify("Marked as done. Learning from your decisions…");
    const poll = setInterval(async () => {
      await get().refreshModel();
      const training = get().model?.training;
      if (training && !training.running) {
        clearInterval(poll);
        if (training.last) get().notify(training.last.message);
        void get().loadPhotos();
      }
    }, 1500);
  },

  async refreshModel() {
    try {
      set({ model: await api.modelStatus() });
    } catch {
      /* shown as "unknown" in the status bar */
    }
  },
}));

/** Follow a shoot's scan: live progress, thumbnails filling in, and a refresh when it ends. */
async function watch(id: number): Promise<void> {
  stopWatching?.();
  clearInterval(refillTimer);
  const { getState: get, setState: set } = useStore;
  let sawRunning = false;
  stopWatching = await api.watchProgress(id, (p: Progress) => {
    if (get().shootId !== id) return;
    set({ progress: p });
    if (p.running) sawRunning = true;
    else if (sawRunning) {
      sawRunning = false;
      clearInterval(refillTimer);
      void get().loadPhotos();
      void get().refreshShoots();
      void get().refreshModel();
    }
  });
  refillTimer = setInterval(() => {
    if (get().progress?.running) void get().loadPhotos();
  }, 2500);
}

function apply(
  set: (partial: Partial<State>) => void,
  get: () => State,
  changes: Change[],
  side: "before" | "after",
  reason?: string,
) {
  const byId = new Map(changes.map((c) => [c.id, c[side]]));
  set({
    photos: get().photos.map((p) => {
      const to = byId.get(p.id);
      return to ? { ...p, user_label: to.label, user_rating: to.rating } : p;
    }),
  });
  for (const c of changes) {
    api.decide([c.id], { label: c[side].label, rating: c[side].rating, reason }).catch((err: Error) => {
      get().notify(`Could not save that decision: ${err.message}`);
      void get().loadPhotos();
    });
  }
}
