"""Dry run: classify the last window_days of photos and write a browsable HTML report. Changes nothing in Immich."""
import base64
import html
from collections import Counter

import httpx

from .immich import ROOT, Immich, home_coords, load_config
from .rules import DROPPED, KEPT, distance_km, metadata_verdict
from .store import Store
from .vlm import JUNK, judge


class NoPreview(Exception):
    pass


def vision(cfg, im, store, asset_id):
    model = cfg["ollama"]["model"]
    v = store.vlm(model, asset_id)
    if v is None:
        try:
            img = im.thumb(asset_id, "preview")
        except httpx.HTTPStatusError as err:
            if err.response.status_code != 404:
                raise
            raise NoPreview from err  # only Immich's 404 means "no preview"; Ollama's 404 is a real failure
        v = judge(cfg, img)
        store.put_vlm(model, asset_id, v)
    return v


def context(cfg, im):
    """What every photo's verdict needs besides the photo itself: excluded albums, picks and OCR hits."""
    excluded = set().union(*[im.album_ids(n) for n in cfg["exclude_albums"]]) if cfg["exclude_albums"] else set()
    return excluded, im.album_ids(cfg["picks_album"]), im.ocr_hits(cfg["ocr_keywords"])


def classify_one(cfg, im, home, store, ctx, a):
    meta = metadata_verdict(a, cfg, home, *ctx)
    km = distance_km(a, home)
    at_home = km is not None and km * 1000 <= cfg["home"]["radius_m"]
    if meta and meta[0] == DROPPED:
        res = meta
    else:  # the vision model vetoes junk even for rule-kept photos, and decides the rest
        try:
            v = vision(cfg, im, store, a["id"])
        except NoPreview:
            # Immich has no preview for this file, so it can never be judged: record that instead of failing on it every run
            return {"asset": a, "verdict": DROPPED, "reason": "no preview image in Immich", "at_home": at_home}
        tag = f"vlm: {v['category']} {v['score']}"
        if v["category"] in JUNK:
            res = DROPPED, tag
        elif meta:
            res = KEPT, f"{meta[1]} ({tag})"
        elif v["score"] >= int(store.get("min_score") or cfg["ollama"]["min_score"]):  # live value from HA, else config
            res = KEPT, tag
        else:
            res = DROPPED, tag
    return {"asset": a, "verdict": res[0], "reason": res[1], "at_home": at_home}


def classify(cfg, im, home, store, assets):
    ctx = context(cfg, im)
    return [classify_one(cfg, im, home, store, ctx, a) for a in assets]


def render(rows, im):
    counts = Counter(r["verdict"] for r in rows)
    reasons = Counter((r["verdict"], r["reason"].split(" (")[0].split(": ")[0] if r["reason"].startswith("ocr") else r["reason"].split(" (")[0]) for r in rows)
    out = ["<meta charset=utf-8><title>Frame Curator dry run</title><style>",
           "body{font:14px system-ui;margin:2rem;background:#fafafa;color:#222}h2{margin-top:2rem}",
           ".g{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:10px}",
           ".t{background:#fff;border:1px solid #ddd;padding:6px;font-size:12px}.t img{width:100%;display:block}",
           ".kept{border-color:#4caf50}.dropped{border-color:#e57373}.uncertain{border-color:#ffb300}</style>",
           f"<h1>Dry run: {len(rows)} photos</h1><p>" + ", ".join(f"{k}: {v}" for k, v in counts.items()) + "</p><ul>"]
    out += [f"<li>{v}: {html.escape(r)} - {n}</li>" for (v, r), n in sorted(reasons.items())] + ["</ul>"]
    for verdict in (KEPT, DROPPED):
        sel = sorted((r for r in rows if r["verdict"] == verdict), key=lambda r: (r["reason"], r["asset"]["fileCreatedAt"]))
        out.append(f"<h2>{verdict} ({len(sel)})</h2><div class=g>")
        for r in sel:
            a = r["asset"]
            try:
                img = base64.b64encode(im.thumb(a["id"])).decode()
            except httpx.HTTPStatusError:  # no thumbnail for this file: show a blank tile rather than lose the whole report
                img = "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
            home = " · home" if r["at_home"] else ""
            out.append(f"<div class='t {verdict}'><img loading=lazy src='data:image/jpeg;base64,{img}'>"
                       f"{a['fileCreatedAt'][:10]}{home}<br>{html.escape(r['reason'])}</div>")
        out.append("</div>")
    return "\n".join(out)


def main():
    cfg = load_config()
    im, home = Immich(cfg), home_coords(cfg)
    rows = classify(cfg, im, home, Store(ROOT / cfg["data_dir"] / "state.db"), im.assets())
    path = ROOT / "reports" / "dryrun.html"
    path.parent.mkdir(exist_ok=True)
    path.write_text(render(rows, im))
    print(Counter(r["verdict"] for r in rows), "->", path)


if __name__ == "__main__":
    main()
