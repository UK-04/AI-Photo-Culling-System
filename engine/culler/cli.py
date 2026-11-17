"""Command line for the engine.

    culler analyze  <folder> [--csv out.csv] [--json out.json]
    culler benchmark <folder> [--truth t.csv | --picks-dir DIR]
    culler export   <folder> --xmp | --copy-to DIR | --csv FILE [--selection keep]
    culler train    [--force]
    culler status
    culler selftest [--vision]
    culler serve    [--port 8765] [--token T] [--ui app/dist]

Everything the desktop app does goes through the same code, so the engine can be
exercised and tested without the app.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import secrets
import socket
import sys
import threading
import time
from collections import Counter
from pathlib import Path

from . import __version__
from .config import Settings, load_settings


def _settings(args: argparse.Namespace) -> Settings:
    return load_settings(
        getattr(args, "config", None),
        data_dir=getattr(args, "data_dir", None),
        workers=getattr(args, "workers", None),
        embedder=getattr(args, "embedder", None),
    )


def _engine(args: argparse.Namespace):
    from .service import Engine

    return Engine(_settings(args))


def _scan(engine, folder: str, quiet: bool = False) -> int:
    shoot_id = engine.repo.add_shoot(folder)
    last = {"stage": "", "shown": 0.0}

    def show(p) -> None:
        if quiet:
            return
        now = time.time()
        if p.stage != last["stage"] or now - last["shown"] > 0.5 or p.stage in ("done", "error", "cancelled"):
            last.update(stage=p.stage, shown=now)
            count = f" {p.done}/{p.total}" if p.total else ""
            print(f"\r\033[K{p.stage:<12}{count}  {p.message}", end="", file=sys.stderr, flush=True)

    result = engine.scan(shoot_id, on_progress=show)
    if not quiet:
        print(file=sys.stderr)
    if result.stage == "error":
        raise SystemExit(f"Scan failed: {result.message}")
    return shoot_id


def cmd_analyze(args: argparse.Namespace) -> int:
    from .export.csv_export import export_csv, to_record

    engine = _engine(args)
    started = time.time()
    shoot_id = _scan(engine, args.folder, args.quiet)
    rows = engine.repo.grid(shoot_id)
    counts = engine.repo.counts(shoot_id)
    labels = Counter(r["label"] for r in rows if r["label"])
    bursts = engine.repo.list_bursts(shoot_id)

    print(f"{counts['total']} photos in {time.time() - started:.1f}s  "
          f"(faces: {engine.face_backend_name}, similarity: {engine.embedder.name})")
    print(f"KEEP {labels.get('KEEP', 0)}   REVIEW {labels.get('REVIEW', 0)}   REJECT {labels.get('REJECT', 0)}   "
          f"unreadable {counts['errors']}   bursts {len(bursts)}")
    reasons = Counter(r["reason_primary"] for r in rows if r["label"] == "REJECT")
    if reasons:
        print("Rejected for: " + ", ".join(f"{k} ({v})" for k, v in reasons.most_common()))
    if args.list:
        for r in rows:
            label = r["label"] or "ERROR"
            reason = r["reason_primary"] or r["error"] or ""
            extra = f", {r['reason_secondary'].lower()}" if r["reason_secondary"] else ""
            conf = f"{r['confidence']:.0%}" if r["confidence"] is not None else "  -"
            print(f"  {label:<7}{conf:>5}  {r['name']:<28} {reason}{extra}")
    if args.csv:
        print(f"CSV:  {export_csv(rows, args.csv)}")
    if args.json:
        Path(args.json).write_text(json.dumps({"counts": counts, "photos": [to_record(r) for r in rows]}, indent=2))
        print(f"JSON: {args.json}")
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from .benchmark import evaluate, format_report, load_truth

    engine = _engine(args)
    truth = load_truth(args.folder, args.truth, args.picks_dir)
    if not truth:
        raise SystemExit("No ground truth found. Use --truth, --picks-dir, or picks/ and rejects/ sub-folders.")
    shoot_id = _scan(engine, args.folder, args.quiet)
    metrics = evaluate(engine.repo.grid(shoot_id), engine.repo.list_bursts(shoot_id), truth)
    print(format_report(metrics))
    if args.json:
        Path(args.json).write_text(json.dumps(metrics, indent=2))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from .export import select_rows
    from .export.csv_export import export_csv
    from .export.folders import copy_photos
    from .export.xmp import export_sidecars

    engine = _engine(args)
    shoot_id = _scan(engine, args.folder, args.quiet)
    rows = [r for r in select_rows(engine.repo.grid(shoot_id), args.selection) if r["status"] == "done"]
    if args.xmp:
        print(json.dumps(export_sidecars(rows).to_dict(), indent=2))
    if args.copy_to:
        print(json.dumps(copy_photos(rows, args.copy_to).to_dict(), indent=2))
    if args.csv:
        print(f"CSV: {export_csv(rows, args.csv)}")
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    result = _engine(args).train(force=args.force)
    print(result.message)
    return 0 if result.status in ("trained", "kept_current") else 1


def cmd_status(args: argparse.Namespace) -> int:
    engine = _engine(args)
    status = engine.model_status()
    print(f"Culler {__version__}   data: {engine.settings.data_dir}")
    print(f"Decisions: {status['decisions']} (first model at {status['needed']})   faces: {status['face_backend']}")
    if status["model"]:
        m = status["model"]
        acc = m["metrics"].get("accuracy")
        print(f"Model {m['version']} ({m['kind']}, {m['n_decisions']} decisions)" + (f", agrees {acc:.0%}" if acc else ""))
    for s in engine.repo.list_shoots():
        print(f"  [{s['id']}] {s['name']:<30} {s['photo_count']:>5} photos  {s['status']}  {s['folder_path']}")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """Prove this build works end to end: scan a generated shoot with worker processes,
    check the results, and check that the vision model's libraries load.

    Run by the build scripts against the packaged engine, where missing libraries and
    broken multiprocessing are the usual failures and unit tests cannot see them.
    """
    import tempfile

    from .service import Engine
    from .synth import make_shoot

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "shoot"
        truth = make_shoot(folder, scenes=14, seed=4, size=(480, 320), corrupt_files=1, defect_share=0.5)
        settings = load_settings(None, data_dir=str(Path(tmp) / "data"), embedder="fallback", workers=2)
        engine = Engine(settings)
        shoot_id = engine.repo.add_shoot(str(folder))
        result = engine.scan(shoot_id)  # the worker-pool path, as the app uses it
        rows = {r["name"]: r for r in engine.repo.grid(shoot_id)}
        problems = []
        if result.stage != "done":
            problems.append(f"scan ended as {result.stage}: {result.message}")
        if len(rows) != len(truth) + 1:
            problems.append(f"expected {len(truth) + 1} photos, found {len(rows)}")
        for p in truth:
            row = rows.get(p.file)
            if row is None or row["label"] is None:
                problems.append(f"{p.file} was not scored")
            elif p.defect in ("blur", "shake", "black") and row["label"] != "REJECT":
                problems.append(f"{p.file} ({p.defect}) was labelled {row['label']}")
        if not all(r.get("category") for r in rows.values() if r["status"] == "done"):
            problems.append("some photos have no topic category")
        print(f"scan: {len(rows)} photos, faces: {engine.face_backend_name}, {len(problems)} problems")

    if args.vision:
        import numpy as np
        from PIL import Image

        from .similarity.embeddings import ClipEmbedder

        emb = ClipEmbedder(settings.clip_model, pretrained=None)  # random weights: loads the libraries, no download
        vecs = emb.embed([Image.new("RGB", (320, 240), (120, 60, 30))])
        text = emb.embed_text(["a group photo of several people"])
        if vecs.shape != (1, emb.dim) or text.shape != (1, emb.dim) or not np.isfinite(vecs).all():
            problems.append("the vision model produced malformed output")
        print(f"vision model libraries: ok ({emb.device})")

    for problem in problems:
        print("FAILED:", problem, file=sys.stderr)
    print("selftest passed" if not problems else "selftest FAILED")
    return 1 if problems else 0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _watch_parent(parent_pid: int | None, watch_stdin: bool) -> None:
    """Exit when the app that started us goes away, so no engine is ever left running."""

    def stdin_watch() -> None:
        try:
            while sys.stdin.buffer.read(4096):
                pass
        except Exception:
            pass
        os._exit(0)

    def pid_watch() -> None:
        while True:
            time.sleep(2.0)
            try:
                os.kill(parent_pid, 0)
            except ProcessLookupError:
                os._exit(0)
            except PermissionError:
                pass

    if watch_stdin:
        threading.Thread(target=stdin_watch, daemon=True).start()
    if parent_pid:
        threading.Thread(target=pid_watch, daemon=True).start()


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .api import create_app

    engine = _engine(args)
    token = args.token or os.environ.get("CULLER_TOKEN") or (None if args.no_token else secrets.token_urlsafe(24))
    port = args.port or _free_port()
    app = create_app(engine, token=token, ui_dir=args.ui)
    _watch_parent(args.parent_pid, args.watch_stdin)
    # One machine-readable line for the desktop shell, then a human one.
    print(json.dumps({"culler": "ready", "port": port, "token": token, "version": __version__}), flush=True)
    if args.ui:
        print(f"Open http://127.0.0.1:{port}/" + (f"?token={token}" if token else ""), file=sys.stderr, flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="culler", description="Local photo-culling engine.")
    parser.add_argument("--version", action="version", version=f"culler {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", help="where the database and caches live")
    common.add_argument("--config", help="TOML file overriding thresholds and weights")
    common.add_argument("--workers", type=int, help="worker processes (default: CPU cores - 1)")
    common.add_argument("--embedder", choices=["auto", "clip", "fallback"], help="similarity model")
    common.add_argument("-q", "--quiet", action="store_true", help="no progress output")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", parents=[common], help="scan a folder and print recommendations")
    p.add_argument("folder")
    p.add_argument("--csv", help="write results to this CSV file")
    p.add_argument("--json", help="write results to this JSON file")
    p.add_argument("--list", action="store_true", help="print one line per photo")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("benchmark", parents=[common], help="compare against a cull you did by hand")
    p.add_argument("folder")
    p.add_argument("--truth", help="CSV with columns file,label")
    p.add_argument("--picks-dir", help="folder containing the photos you kept")
    p.add_argument("--json", help="write the metrics to this JSON file")
    p.set_defaults(func=cmd_benchmark)

    p = sub.add_parser("export", parents=[common], help="write XMP sidecars, copy picks, or save a CSV")
    p.add_argument("folder")
    p.add_argument("--xmp", action="store_true", help="write .xmp sidecars next to RAW files")
    p.add_argument("--copy-to", help="copy the selection into this folder")
    p.add_argument("--csv", help="write the selection to this CSV file")
    p.add_argument("--selection", choices=["picked", "keep", "decided", "all"], default="all")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("train", parents=[common], help="train the personal model from your decisions")
    p.add_argument("--force", action="store_true", help="replace the current model even if it scores higher")
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("status", parents=[common], help="show shoots and model status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("selftest", help="check that this build of the engine works")
    p.add_argument("--vision", action="store_true", help="also load the vision model's libraries")
    p.set_defaults(func=cmd_selftest)

    p = sub.add_parser("serve", parents=[common], help="run the local API for the desktop app")
    p.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: any free port)")
    p.add_argument("--token", help="access token (default: a random one, printed at start)")
    p.add_argument("--no-token", action="store_true", help="development only: no access token")
    p.add_argument("--ui", help="folder with the built web UI to serve at /")
    p.add_argument("--parent-pid", type=int, help="exit when this process exits")
    p.add_argument("--watch-stdin", action="store_true", help="exit when stdin closes")
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()  # required for worker processes in the packaged app
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
