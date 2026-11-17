# Culler

A Mac app that culls a photo shoot into KEEP / REVIEW / REJECT, says why, stacks bursts,
and learns your taste from every decision. Everything runs on your Mac. Originals are
never modified, moved or deleted.

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
