import { pickFolder, pickPhotos } from "./api";
import { useStore } from "./store";

export async function chooseAndOpenFolder(): Promise<void> {
  const folder = await pickFolder("Choose a folder of photos");
  if (folder) await useStore.getState().openFolder(folder);
}

export async function chooseAndOpenPhotos(): Promise<void> {
  try {
    const files = await pickPhotos("Select photos");
    if (files.length) await useStore.getState().openPhotos(files);
  } catch (err) {
    useStore.getState().notify(`Could not open the photo picker: ${(err as Error).message}`);
  }
}
