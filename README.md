# Culler

**Cull a photo shoot in minutes, on your own Mac.**

### [⬇ Download Culler for Mac](https://github.com/UK-04/AI-Photo-Culling-System/releases/latest/download/Culler.dmg)

Free. Needs an Apple Silicon Mac (M1 or newer) with macOS 14 or later. The link always gives you the newest version.

Culler goes through a shoot the way you would on a first pass. It sorts every photo into
**Keep**, **Review** or **Reject**, tells you why in plain words, and lets you confirm or
override each call with one key. Everything runs on your Mac: nothing is uploaded, and your
original files are never changed, moved or deleted.

## What it does

- **Catches the misses.** Flags out-of-focus frames, camera shake, focus that landed on the
  background, closed eyes, blown-out faces and accidental frames such as a lens cap left on.
- **Stacks bursts.** Groups frames shot a split second apart into one stack, with the sharpest,
  eyes-open frame on top. Click the number on a stack to see every frame.
- **Sorts by topic.** Pick the kind of shoot (wedding, event, portrait session, travel or general)
  and Culler groups photos into topics such as group photos, couple portraits, ceremony,
  details or landmarks. Photos unlike the rest of the shoot are flagged as off-topic.
- **Rates how fixable a photo is.** For underexposed, overexposed or slightly soft photos, it
  estimates whether editing can save them, from "Easy fix" to "Not fixable".
- **Learns your taste.** Every pick and reject teaches it. After about 300 decisions it starts
  ranking new shoots the way you cull.
- **Fast review.** P picks, X rejects, 1 to 5 sets stars, arrow keys move. Click to zoom to
  100%, drag to look around, compare burst frames side by side, rotate with [ and ].
- **Hands off to Lightroom.** Writes colour labels and stars into sidecar files Lightroom reads,
  or copies your picks (optionally sorted into a folder per topic) to wherever you want them.
- **Updates itself.** When a new version is out, Culler offers to install it and restart.

## Installing

1. Open the downloaded **Culler.dmg** and drag **Culler** into **Applications**.
2. Open Culler. The first time, macOS says it cannot check the app: click **Done**.
3. Open **System Settings → Privacy & Security**, scroll down, click **Open Anyway** next to
   Culler, and confirm.

You only do this once. Culler is not yet registered with Apple, which is why macOS asks.

## For developers

- `engine/`  Python: analysis, burst grouping, scoring, the personal model, exports, local API, CLI
- `app/`     the interface (React) and the Mac shell (Tauri)
- `scripts/` build, sign and notarize
- `docs/`    what was built, what is verified, and every non-obvious decision

Read `docs/PROGRESS.md` first: it says exactly what has been tested and what still needs a Mac.

## Try it in five minutes (no app build needed)

```bash
./scripts/fetch_models.sh                 # two small face models
pip install -e "engine[dev]"              # add ",clip" for the real similarity model
culler analyze ~/Pictures/SomeShoot --list
```

To use the full interface in a browser:

```bash
./scripts/dev.sh                          # then open the URL it prints
```

## Check it against a cull you already did

This is the test that matters. Point it at a past shoot and at the folder of photos you kept:

```bash
culler benchmark ~/Pictures/SmithWedding --picks-dir ~/Pictures/SmithWedding-Selects
```

It reports how often a REJECT was really a reject (target: 85% or more), how many of your
rejects sat in the softest quarter of the shoot, and how often the top frame of a burst was
one you kept. Tune `Thresholds` in `engine/culler/config.py` (or a TOML file passed with
`--config`) until the numbers hold on three shoots.

## Build the Mac app

On an Apple Silicon Mac:

```bash
./scripts/check_mac.sh                    # says what is missing and how to install it
./scripts/build_engine.sh                 # bundles the Python engine
./scripts/build_app.sh                    # Culler.app and a .dmg
```

For a signed, notarized DMG that opens on any Mac, set `APPLE_SIGNING_IDENTITY` first and
run `./scripts/notarize.sh` afterwards (needs an Apple Developer account).

## Keyboard

P pick, X reject, U unflag, 1-5 stars, arrows to move, Space grid/loupe, Z zoom on the main
face, C compare a burst, S open a stack, Tab next photo needing a decision, ⌘Z undo, ⌘E export.

## Lightroom

Lightroom keeps pick/reject flags only in its own catalog, so no outside app can set them.
Culler writes colour labels (green keep, yellow review, red reject) and your stars into
`.xmp` sidecars for RAW files. For JPEGs, Lightroom ignores sidecars, so use "Copy to a
folder": the copies carry the label and stars inside the file.

## Tests

```bash
cd engine && pytest          # 94 tests
cd app && npm test && npm run build
```
