"""Phase 0 check: confirm the Immich v3.x endpoints and key scopes we rely on. Prints status codes and counts only."""
import os
import sys
from pathlib import Path

import httpx
import yaml

root = Path(__file__).resolve().parent.parent
for line in (root / ".env").read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

cfg = yaml.safe_load((root / "config.yaml").read_text())
base = cfg["immich"]["url"].rstrip("/") + "/api"
c = httpx.Client(base_url=base, headers={"x-api-key": os.environ["IMMICH_CURATOR_KEY"]}, timeout=30)
failed = 0


def check(name, method, path, **kw):
    global failed
    r = c.request(method, path, **kw)
    ok = r.status_code < 300
    failed += not ok
    print(f"{'OK  ' if ok else 'FAIL'} {r.status_code} {name}" + ("" if ok else f"  {r.text[:150]}"))
    return r.json() if ok and "json" in r.headers.get("content-type", "") else None


print("server version:", httpx.get(base + "/server/version", timeout=30).json())
tags = check("list tags (tag.read)", "GET", "/tags")
print("   tags:", len(tags or []))
check("list albums (album.read)", "GET", "/albums")
check("list people (person.read)", "GET", "/people", params={"size": 1})
res = check("metadata search IMAGE (asset.read)", "POST", "/search/metadata", json={"type": "IMAGE", "size": 1, "withExif": True})
items = ((res or {}).get("assets") or {}).get("items") or []
check("smart search with ocr filter", "POST", "/search/smart", json={"query": "a landscape", "type": "IMAGE", "size": 1, "ocr": "x"})
check("smart search plain", "POST", "/search/smart", json={"query": "a landscape", "type": "IMAGE", "size": 1})
if items:
    a = items[0]
    print("   asset keys:", sorted(a.keys()))
    print("   exif keys:", sorted((a.get("exifInfo") or {}).keys()))
    check("faces for asset (face.read)", "GET", "/faces", params={"id": a["id"]})
    check("preview thumbnail (asset.view)", "GET", f"/assets/{a['id']}/thumbnail", params={"size": "preview"})
else:
    print("no image found; skipping asset checks")
sys.exit(1 if failed else 0)
