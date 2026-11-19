"""Judge photos older than the curator's window, newest first, so the frame has more than the last 60 days to draw on.

Only keepers get a frame/yes tag; rejects are recorded in the local database. Safe to stop and rerun: every judged photo
is recorded as it goes, so the next run continues where this one ended. --sample judges a random set and writes an HTML
report without tagging or recording anything."""
import argparse
import json
import random
import sys
import time
from datetime import UTC, datetime

from .dryrun import classify_one, context, render
from .immich import ROOT, Immich, home_coords, load_config
from .lock import Busy, job_lock
from .rules import KEPT
from .store import Store

YES, BLOCK = "frame/yes", "frame/block"
BATCH = 50  # keepers are tagged in batches, so a crash loses at most this much work
MAX_FAILURES = 3  # consecutive failures (Ollama or Immich down) end the run instead of skipping photos


def run(hours, limit, sample, now=time.time, log=print):
    cfg = load_config()
    im, store = Immich(cfg), Store(ROOT / cfg["data_dir"] / "state.db")
    home, ctx = home_coords(cfg), context(cfg, im)
    deadline = now() + hours * 3600
    done = store.applied_ids()
    blocked = im.tagged_ids(im.tag_id(BLOCK))
    stats = {"judged": 0, "kept": 0, "failures": 0}
    pending, started, state = [], now(), {"stopped": None, "oldest": None}

    def flush():
        if pending:
            im.tag_assets(im.tag_id(YES, create=True), [r["asset"]["id"] for r in pending])
            for r in pending:
                store.put_applied(r["asset"]["id"], YES, r["reason"], policy="yes_only")
            pending.clear()

    def process(row):
        a = row["asset"]
        stats["judged"] += 1
        state["oldest"] = a["localDateTime"][:10]
        if row["verdict"] == KEPT:
            stats["kept"] += 1
            pending.append(row)
            if len(pending) >= BATCH:
                flush()
        else:
            store.put_applied(a["id"], "frame/no", row["reason"], policy="yes_only")  # not tagged: recorded here only
        if stats["judged"] % 100 == 0:
            log(f"judged {stats['judged']}, kept {stats['kept']}, now at {state['oldest']}, "
                f"{(now() - started) / stats['judged']:.1f} s per photo")

    rows = []
    for page in im.old_assets():
        todo = [a for a in page if a["id"] not in done and a["id"] not in blocked]
        if sample:
            rows += todo  # collected first: a sample must be drawn from the whole library, not just the newest page
            continue
        for a in todo:
            if now() > deadline or (limit and stats["judged"] >= limit):
                state["stopped"] = "time" if now() > deadline else "limit"
                break
            try:
                row = classify_one(cfg, im, home, store, ctx, a)
            except Exception as err:  # noqa: BLE001 - any failure to judge one photo leaves it for the next run
                stats["failures"] += 1
                log(f"could not judge {a['id'][:8]}: {err}")
                if stats["failures"] >= MAX_FAILURES:
                    state["stopped"] = "failures"
                    break
                continue
            stats["failures"] = 0
            process(row)
        if state["stopped"]:
            break
    if sample:
        return write_sample(cfg, im, home, store, ctx, rows, sample, deadline, now, log)
    flush()
    progress = json.loads(store.get("backfill") or "{}")
    progress.update(judged=progress.get("judged", 0) + stats["judged"], kept=progress.get("kept", 0) + stats["kept"],
                    last_run=datetime.now(UTC).isoformat(), oldest_reached=state["oldest"] or progress.get("oldest_reached"),
                    finished=state["stopped"] is None)
    store.put("backfill", json.dumps(progress))
    log(f"{'finished: nothing left to judge' if state['stopped'] is None else 'stopped (' + state['stopped'] + ')'}: judged "
        f"{stats['judged']} this run, kept {stats['kept']}; oldest reached {state['oldest']}; "
        f"total so far {progress['judged']} judged, {progress['kept']} kept")
    return 2 if state["stopped"] == "failures" else 0


def write_sample(cfg, im, home, store, ctx, assets, n, deadline, now, log):
    rows = []
    for a in random.Random(1).sample(assets, min(n, len(assets))):
        if now() > deadline:
            break
        rows.append(classify_one(cfg, im, home, store, ctx, a))
    path = ROOT / "reports" / "backfill-sample.html"
    path.parent.mkdir(exist_ok=True)
    path.write_text(render(rows, im))
    kept = sum(r["verdict"] == KEPT for r in rows)
    log(f"sample of {len(rows)} from {len(assets)} unjudged photos: {kept} kept -> {path} (nothing tagged or recorded)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="really backfill: tag keepers and record verdicts")
    ap.add_argument("--hours", type=float, default=5.5, help="stop after this long")
    ap.add_argument("--limit", type=int, default=0, help="stop after this many photos (0: no limit)")
    ap.add_argument("--sample", type=int, default=0, help="judge N random unjudged photos and write a report; changes nothing")
    args = ap.parse_args()
    if not args.apply and not args.sample:
        sys.exit("nothing to do: pass --sample N for a report or --apply to backfill")
    if not args.apply:
        sys.exit(run(args.hours, args.limit, args.sample))
    try:
        with job_lock(ROOT / load_config()["data_dir"]):
            sys.exit(run(args.hours, args.limit, args.sample))
    except Busy:
        print("already running")
        sys.exit(3)
