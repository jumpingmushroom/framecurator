import io
import random
from datetime import datetime

from PIL import Image

from framecurator.frame.render import render
from framecurator.frame.select import pick

NOW = datetime(2026, 10, 26)


def a(i, date, fav=False):
    return {"id": i, "localDateTime": date, "isFavorite": fav}


def jpeg(w, h, color=(200, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


def test_render_size_for_all_shapes():
    for w, h in ((3000, 2000), (2000, 3000), (1000, 1000), (4000, 3000)):
        out = Image.open(io.BytesIO(render(jpeg(w, h), [], 1920, 1200)))
        assert out.size == (1920, 1200)


def test_face_moves_the_crop():
    img = Image.new("RGB", (4000, 2000), "blue")
    img.paste(Image.new("RGB", (400, 400), "red"), (3500, 800))  # red marks a face on the far right
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    face = {"boundingBoxX1": 3500, "boundingBoxY1": 800, "boundingBoxX2": 3900, "boundingBoxY2": 1200, "imageWidth": 4000, "imageHeight": 2000}
    with_face = Image.open(io.BytesIO(render(buf.getvalue(), [face], 1920, 1200)))
    assert with_face.getpixel((1700, 600))[0] > 150  # red visible when faces steer the crop
    # 2:1 photo into 16:10 keeps 80% so it crops; without faces the right edge is centred away
    centred = Image.open(io.BytesIO(render(buf.getvalue(), [], 1920, 1200)))
    assert centred.getpixel((1700, 600))[0] < 150


MIX = {"on_this_day": 0.3, "favorites_picks": 0.2, "recent_30d": 0.35}


def test_pick_skips_shown_and_falls_back():
    pool = [a("x", "2026-10-20T10:00:00"), a("y", "2020-01-01T10:00:00")]
    got, _ = pick(pool, {"x"}, set(), MIX, "mixed", NOW, random.Random(1))
    assert got["id"] == "y"
    got, _ = pick(pool, {"x", "y"}, set(), MIX, "mixed", NOW, random.Random(1))  # all shown: repeats allowed
    assert got["id"] in {"x", "y"}
    assert pick([], set(), set(), MIX, "mixed", NOW) is None


def test_modes():
    pool = [a("new", "2026-10-20T10:00:00"), a("old", "2020-05-05T10:00:00"), a("memory", "2024-10-25T10:00:00"), a("fav", "2019-01-01T10:00:00", True)]
    assert pick(pool, set(), set(), MIX, "recent", NOW)[0]["id"] == "new"
    assert pick(pool, set(), set(), MIX, "memories", NOW)[0]["id"] == "memory"
    assert pick(pool, set(), set(), MIX, "picks", NOW)[0]["id"] == "fav"
    assert pick(pool, set(), {"old"}, MIX, "picks", NOW, random.Random(0))[1] == "favorites_picks"
    assert pick(pool[1:2], set(), set(), MIX, "memories", NOW)[1] == "library"  # empty bucket falls back


def test_all_zero_weights_fall_back_to_the_whole_pool():
    pool = [a("x", "2026-10-20T10:00:00"), a("y", "2020-01-01T10:00:00")]
    got, bucket = pick(pool, set(), set(), {"recent_30d": 0, "library": 0}, "mixed", NOW, random.Random(1))
    assert bucket == "library" and got["id"] in {"x", "y"}
