# Decisions

Choices made where the build spec was silent, or where it had to change. Newest concerns first.

## Changes from the spec

1. **Lightroom flags cannot be exported.** The spec asked for "XMP flags". Lightroom Classic
   stores pick/reject flags only in its catalog, never in XMP. Decisions are exported as colour
   labels (Green keep, Yellow review, Red reject) plus star ratings; rejects also get
   `xmp:Rating = -1`, which Bridge and Photo Mechanic show as "Reject". In Lightroom: filter
   by red label, select all, press X.
2. **Sidecars are written for RAW only.** Lightroom ignores `.xmp` sidecars next to JPEG, HEIC
   and PNG. Since originals are never modified, those formats get their rating only in copies
   ("Copy to a folder" embeds XMP in the JPEG copy without re-encoding the image).
3. **Face detection is YuNet, then MediaPipe on each face crop.** MediaPipe's own detector is
   built for close faces and misses small ones in event photos. YuNet finds faces; the
   MediaPipe Face Landmarker measures eyes on each crop (blink scores plus eye aspect ratio).
   Without the landmark model, eye state is "unknown" and nothing is rejected for eyes.
4. **No Tailwind, no TanStack Query.** One hand-written stylesheet with colour tokens and one
   Zustand store do the job with fewer moving parts. TanStack Virtual is used for the grid.
5. **A fallback similarity model exists.** If PyTorch or the CLIP weights are missing, a built-in
   512-number descriptor (layout, colour, edges) groups bursts. Vectors are stored with the
   model's name and never mixed. The personal model is much stronger with CLIP.
6. **"Sharp" is learned per shoot.** The spec's "bottom 10% is rejected" would throw away 10%
   of a perfectly sharp shoot. A reject needs both: bottom 10% of the shoot AND under 20% of
   the shoot's own sharp level (its 75th percentile).
7. **Weaker burst frames are REVIEW unless they fail technically.** A burst frame that is
   clearly out of focus is still rejected; being a duplicate alone never rejects.
8. **Badly under- or overexposed frames are REVIEW**, never an automatic KEEP or REJECT,
   because low-key and high-key photos are a style. Only near-black or near-white frames
   (lens cap, misfire) are rejected as blank.
9. **Removing a shoot archives it.** Its decisions stay, because the model learns from them
   and the decisions table is append-only (enforced by database triggers).
10. `export/csv.py` is named `csv_export.py`, and `schema.sql` lives in `db/migrations/0001_init.sql`.

## Other choices

- **App name "Culler", bundle id `com.usmankhan.culler`.** Placeholders. Change in
  `app/src-tauri/tauri.conf.json` and `engine/culler/config.py` before the first release;
  the bundle id cannot change after people install it without losing their data folder.
- **Sharpness is contrast-normalized** (Laplacian variance divided by intensity variance) so
  dark frames are not mistaken for soft ones, and judged on a log scale.
- **Motion blur** is detected from the anisotropy of fine-detail gradients, and discounts the
  sharpness score, because plain Laplacian variance rates shaken frames as fairly sharp.
- **RAW + JPEG pairs** count as one photo; the JPEG is used as the preview.
- **A moved or renamed file keeps its decisions** (matched by content hash within the shoot).
- **Personal model**: logistic regression from 300 decisions, gradient boosting from 2,000,
  calibrated, validated leave-one-shoot-out, shipped only if it does not lose to the current
  model on the newest shoot. Taste alone can reject only once a model exists, and a hard
  technical reject is softened to REVIEW when the model is confident you would keep it.
- **Engine and UI can run without the shell** (`scripts/dev.sh`), which is how the interface
  was tested, and gives a browser version for free.
- **Model files are not in git.** `scripts/fetch_models.sh` downloads them from OpenCV's and
  Google's official locations. The YuNet hash is pinned; the landmark model's is not yet.
- **Thresholds are untuned defaults.** They were set on synthetic and sample images. Tune on
  the owner's benchmark shoots with `culler benchmark`.
