// Talks to the local engine. In the desktop app the port and token come from the
// Tauri shell; in a plain browser they come from the page URL (?port=&token=) or,
// when the engine itself serves this page, from the same origin.
import type { ModelStatus, Photo, PhotoDetail, Counts, Progress, Shoot, UserLabel } from "./types";

interface Connection {
  base: string;
  token: string;
}

let connection: Promise<Connection> | null = null;

export const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

async function connect(): Promise<Connection> {
  if (isTauri) {
    const { invoke } = await import("@tauri-apps/api/core");
    for (let attempt = 0; attempt < 240; attempt++) {
      const info = await invoke<{ port: number; token: string } | null>("engine_info");
      if (info) {
        const base = `http://127.0.0.1:${info.port}`;
        try {
          if ((await fetch(`${base}/health`)).ok) return { base, token: info.token };
        } catch {
          /* engine still starting */
        }
      }
      await new Promise((r) => setTimeout(r, 250));
    }
    throw new Error("The analysis engine did not start. Quit and reopen the app.");
  }
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token") ?? sessionStorage.getItem("culler-token") ?? "";
  if (token) sessionStorage.setItem("culler-token", token);
  const port = params.get("port");
  return { base: port ? `http://127.0.0.1:${port}` : window.location.origin, token };
}

function conn(): Promise<Connection> {
  if (!connection) connection = connect();
  return connection;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { base, token } = await conn();
  const res = await fetch(base + path, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Culler-Token": token, ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

let imageBase: Connection | null = null;
conn().then((c) => (imageBase = c)).catch(() => undefined);

/** URL for an <img>. The hash makes it cacheable forever and fresh when the file changes. */
export function imageUrl(photo: { id: number; file_hash: string | null }, kind: "thumb" | "preview"): string {
  if (!imageBase) return "";
  return `${imageBase.base}/photos/${photo.id}/${kind}?token=${encodeURIComponent(imageBase.token)}&v=${photo.file_hash ?? ""}`;
}

export interface ExportRequest {
  kind: "xmp" | "folder" | "csv";
  selection: "picked" | "keep" | "decided" | "all";
  dest?: string;
}
export type ExportReport = Record<string, unknown> & { kind: string; selected: number; failed?: string[] };

export const api = {
  ready: () => conn().then(() => undefined),
  shoots: () => request<Shoot[]>("/shoots"),
  addShoot: (folder_path: string) => post<Shoot>("/shoots", { folder_path }),
  removeShoot: (id: number) => request<{ ok: boolean }>(`/shoots/${id}`, { method: "DELETE" }),
  scan: (id: number) => post<Progress>(`/shoots/${id}/scan`),
  cancel: (id: number) => post<Progress>(`/shoots/${id}/cancel`),
  photos: (id: number) => request<{ photos: Photo[]; counts: Counts }>(`/shoots/${id}/photos`),
  photo: (id: number) => request<PhotoDetail>(`/photos/${id}`),
  teach: (id: number) => request<{ photo_ids: number[] }>(`/shoots/${id}/teach?limit=60`),
  decide: (ids: number[], change: { label?: UserLabel; rating?: number; reason?: string }) =>
    post<{ results: unknown[] }>("/decisions", { photo_ids: ids, ...change }),
  finish: (id: number) => post<{ ok: boolean }>(`/shoots/${id}/finish`),
  exportShoot: (id: number, body: ExportRequest) => post<ExportReport>(`/shoots/${id}/export`, body),
  modelStatus: () => request<ModelStatus>("/model/status"),
  train: () => post<unknown>("/model/train", { force: false }),

  /** Live scan progress. Returns a function that stops listening. */
  async watchProgress(id: number, onUpdate: (p: Progress) => void): Promise<() => void> {
    const { base, token } = await conn();
    const source = new EventSource(`${base}/shoots/${id}/progress?token=${encodeURIComponent(token)}`);
    source.onmessage = (event) => {
      const progress = JSON.parse(event.data) as Progress;
      onUpdate(progress);
      if (!progress.running) source.close();
    };
    source.onerror = () => source.close();
    return () => source.close();
  },
};

/** Ask for a folder: native dialog in the app, a typed path in a browser. */
export async function pickFolder(title: string): Promise<string | null> {
  if (isTauri) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const picked = await open({ directory: true, multiple: false, title });
    return typeof picked === "string" ? picked : null;
  }
  return window.prompt(`${title}\n\nPaste the full folder path:`)?.trim() || null;
}
