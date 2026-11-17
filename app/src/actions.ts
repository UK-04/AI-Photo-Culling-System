import { pickFolder } from "./api";
import { useStore } from "./store";

export async function chooseAndOpenFolder(): Promise<void> {
  const folder = await pickFolder("Choose a folder of photos");
  if (folder) await useStore.getState().openFolder(folder);
}
