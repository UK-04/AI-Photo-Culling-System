# Progress

Built 2026-11-16 in a Linux sandbox. That matters: everything that can run on Linux was
run and tested; everything that needs macOS, real face photos, or the owner's shoots is
written but marked below as not yet verified.

## Status by phase

| Phase | State | Evidence |
| --- | --- | --- |
| 0 Setup | Done, except benchmark set | Repo, lint, CI file. Needs 3 culled shoots from the owner. `docs/CRITERIA.md` is a template to fill in. |
| 1 Ingestion | Done | Tests for JPEG, PNG, HEIC, orientation, corrupt files. Real NEF and CR2 files loaded from their embedded previews in 150-200 ms each, EXIF read. |
| 2 Technical analysis | Done; eye check unverified | Sharpness, motion blur, exposure tested on synthetic defects. Face detection (YuNet) checked on a test portrait: found, correct box, small face found, no false hit. **Closed-eye detection has never run**: its model file could not be downloaded here. |
| 3 Bursts | Done with fallback similarity | Synthetic bursts: all found, best frame correct. **CLIP path ran only with random weights** (weights could not be downloaded), so its 0.92 threshold is untuned. |
| 4 Rule scoring | Done on synthetic data | Synthetic shoot: REJECT precision 100%, burst pick 100%. Says nothing yet about real photos. |
| 5 Engine API | Done | 9 API tests: auth, scan, progress stream, decisions, exports, images. Cancel and resume tested in the engine. |
| 6 App shell | **Written, never compiled** | Rust + Tauri config could not be built on Linux (no macOS target, no WebKit). Expect small compile fixes. |
| 7 Review UI | Done in a browser | Type-checks, builds, 9 logic tests. Driven in headless Chrome against the real engine: keyboard pick/reject/rate, undo, compare, loupe, zoom, filters, export dialog, light and dark. Not yet tried at 5,000 photos or inside the Mac window. |
| 8 Decisions and export | Done; Lightroom import unverified | Append-only log enforced by the database. XMP merge keeps develop settings byte-for-byte. JPEG copies carry XMP that Pillow reads back. **Not yet opened in Lightroom.** |
| 9 Personal model | Done on synthetic taste | Three synthetic shoots (about 330 decisions) with a made-up taste; on a fourth unseen shoot the model beats rules by more than 10 points. Real taste is harder; unverified. |
| 10 Performance | Partly measured | 24 MP JPEGs: 0.36 s per photo on ONE core here; rescan of an analyzed shoot about 1 s. An M1 has 8 cores, so 2,000 photos should land well under 10 minutes, but that is an estimate until run on a Mac. Memory and the 5,000-photo targets are unmeasured. |
| 11 Polish and release | Scripts written, not run | PyInstaller spec, build, signing and notarization scripts. Needs a Mac and an Apple Developer account. No onboarding beyond the welcome screen; no auto-update yet. |

## Definition of done: where it stands

- Signed, notarized DMG: **not done** (needs a Mac and a Developer account).
- 2,000 JPGs in under 10 minutes on an M1: **not measured on a Mac**.
- Personal model beats rules after 5 real shoots: **not testable until the owner culls 5 shoots**.
- Export to Lightroom: built, with one change from the spec. Lightroom does not read pick/reject
  flags from XMP at all, so decisions go out as colour labels plus stars. See DECISIONS.md.

## First things to do on a Mac

1. `./scripts/fetch_models.sh`, check the printed hash of `face_landmarker.task`, pin it in the script.
2. `pip install -e "engine[dev,clip]" && cd engine && pytest`.
3. `culler benchmark <past shoot> --picks-dir <your selects>` on three shoots; tune thresholds.
   Look hardest at "Eyes closed" rejects, since that path is untested.
4. `cd app && npm install && npm run tauri dev` with an engine running (see `src-tauri/src/lib.rs`
   for `CULLER_DEV_ENGINE`); fix any Rust compile errors.
5. `./scripts/build_engine.sh && ./scripts/build_app.sh`.

## Open issues

- The sidecar launcher (a small shell script that starts the bundled engine folder) is the
  least certain part of packaging. If Tauri or codesign objects, switch the PyInstaller build
  to one-file mode and ship that binary directly as the sidecar.
- Thumbnails come from a 2048 px preview. Critical focus is judged at that size, not at 100%
  of a 45 MP original; very slight misfocus can pass. The preview size is a setting.
- A shoot whose whole folder is renamed is treated as a new shoot. Its old decisions still
  train the model, but they do not reappear on the photos.
