"""Fit a photo to the panel: face-aware crop when little is lost, otherwise a blurred fill."""
import io

from PIL import Image, ImageFilter, ImageOps

MIN_KEPT_AREA = 0.8  # crop only if at least this share of the photo survives


def render(jpeg, faces, width, height, quality=88):
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(jpeg))).convert("RGB")
    w, h = img.size
    target = width / height
    ar = w / h
    if min(ar, target) / max(ar, target) >= MIN_KEPT_AREA:
        out = _cover(img, faces, width, height)
    else:
        bg = ImageOps.fit(img, (width, height)).filter(ImageFilter.GaussianBlur(40))
        bg = Image.blend(bg, Image.new("RGB", (width, height), "black"), 0.35)
        fg = ImageOps.contain(img, (width, height))
        bg.paste(fg, ((width - fg.width) // 2, (height - fg.height) // 2))
        out = bg
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _cover(img, faces, width, height):
    w, h = img.size
    scale = max(width / w, height / h)
    big = img.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    cx, cy = 0.5, 0.5
    faces = [f for f in faces if f.get("imageWidth")]
    if faces:  # centre the crop on the mean of all face centres
        cx = sum((f["boundingBoxX1"] + f["boundingBoxX2"]) / 2 / f["imageWidth"] for f in faces) / len(faces)
        cy = sum((f["boundingBoxY1"] + f["boundingBoxY2"]) / 2 / f["imageHeight"] for f in faces) / len(faces)
    left = min(max(round(cx * big.width - width / 2), 0), big.width - width)
    top = min(max(round(cy * big.height - height / 2), 0), big.height - height)
    return big.crop((left, top, left + width, top + height))
