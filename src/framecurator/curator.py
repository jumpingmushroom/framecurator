"""Judge new photos and tag them frame/yes or frame/no in Immich. Plans only unless --apply is given."""
import argparse
import sys
from collections import Counter

from .dryrun import classify
from .immich import ROOT, Immich, home_coords, load_config
from .lock import Busy, job_lock
from .rules import KEPT
from .store import Store

YES, NO, BLOCK = "frame/yes", "frame/no", "frame/block"


def run(apply):
    cfg = load_config()
    im, store = Immich(cfg), Store(ROOT / cfg["data_dir"] / "state.db")
    blocked = im.tagged_ids(im.tag_id(BLOCK))
    # a photo already handled is never touched again, so hand edits to its tags survive
    new = [a for a in im.assets() if a["id"] not in store.applied_ids() and a["id"] not in blocked]
    rows = classify(cfg, im, home_coords(cfg), store, new)
    print(f"{len(new)} new photos:", dict(Counter(r["verdict"] for r in rows)))
    if not apply:
        print("dry run: nothing written (use --apply)")
        return
    write(im, store, rows)
    print(f"{len(rows)} photos tagged")


def write(im, store, rows):
    for tag, keep in ((YES, True), (NO, False)):
        sel = [r for r in rows if (r["verdict"] == KEPT) == keep]
        if sel:
            im.tag_assets(im.tag_id(tag, create=True), [r["asset"]["id"] for r in sel])
            for r in sel:
                store.put_applied(r["asset"]["id"], tag, r["reason"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    apply = ap.parse_args().apply
    if not apply:
        run(False)
    else:
        try:
            with job_lock(ROOT / load_config()["data_dir"]):
                run(True)
        except Busy:
            print("already running")
            sys.exit(3)
