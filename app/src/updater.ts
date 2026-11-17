// In-app updates. The desktop shell checks GitHub Releases for a newer build, verifies its
// signature against the key baked into the app, replaces the app in place and restarts.
// Outside the desktop app (browser mode) every function here does nothing.
import { isTauri } from "./api";

export interface AvailableUpdate {
  version: string;
  notes: string;
  /** Download and install, reporting progress from 0 to 1 (null while the size is unknown). */
  install(onProgress: (fraction: number | null) => void): Promise<void>;
}

export async function checkForUpdate(): Promise<AvailableUpdate | null> {
  if (!isTauri) return null;
  const { check } = await import("@tauri-apps/plugin-updater");
  const update = await check();
  if (!update) return null;
  return {
    version: update.version,
    notes: update.body ?? "",
    async install(onProgress) {
      let total = 0;
      let done = 0;
      await update.downloadAndInstall((event) => {
        if (event.event === "Started") {
          total = event.data.contentLength ?? 0;
          onProgress(total ? 0 : null);
        } else if (event.event === "Progress") {
          done += event.data.chunkLength;
          onProgress(total ? Math.min(1, done / total) : null);
        } else if (event.event === "Finished") {
          onProgress(1);
        }
      });
      const { relaunch } = await import("@tauri-apps/plugin-process");
      await relaunch();
    },
  };
}

export async function appVersion(): Promise<string | null> {
  if (!isTauri) return null;
  const { getVersion } = await import("@tauri-apps/api/app");
  return getVersion();
}
