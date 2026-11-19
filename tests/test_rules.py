from framecurator.rules import DROPPED, KEPT, km_between, metadata_verdict

CFG = {"screenshot_name": r"(?i)screenshot|\.png$", "travel_km": 30}
HOME = (59.0, 10.0)


def asset(**kw):
    a = {"id": "a", "visibility": "timeline", "originalFileName": "IMG_1.jpg", "people": [],
         "exifInfo": {"make": "Apple", "model": "iPhone", "latitude": 59.0, "longitude": 10.0}}
    a.update(kw)
    return a


def verdict(a, excluded=(), picks=(), ocr=None):
    return metadata_verdict(a, CFG, HOME, set(excluded), set(picks), ocr or {})


def test_plain_home_photo_goes_to_clip():
    assert verdict(asset()) is None


def test_drops():
    assert verdict(asset(isArchived=True))[0] == DROPPED
    assert verdict(asset(), excluded=["a"])[1] == "in excluded album"
    assert verdict(asset(originalFileName="Screenshot_1.jpg"))[0] == DROPPED
    assert verdict(asset(exifInfo={}))[1] == "no camera make/model"
    assert verdict(asset(), ocr={"a": "kvittering"})[1] == "ocr: kvittering"


def test_keeps():
    assert verdict(asset(people=[{"name": "Kari"}])) == (KEPT, "named person")
    assert verdict(asset(people=[{"name": ""}])) is None  # unnamed face is not enough
    assert verdict(asset(isFavorite=True))[0] == KEPT
    assert verdict(asset(), picks=["a"])[0] == KEPT
    far = asset(exifInfo={"make": "x", "latitude": 48.8, "longitude": 2.3})
    assert verdict(far)[0] == KEPT


def test_exclusion_beats_named_person():
    assert verdict(asset(people=[{"name": "Kari"}]), excluded=["a"])[0] == DROPPED


def test_no_gps_goes_to_clip():
    assert verdict(asset(exifInfo={"make": "x"})) is None


def test_distance():
    assert 110 < km_between(0, 0, 1, 0) < 112

