# Slideshow

The slideshow page shows the frame in any browser, for example on a tablet without Home Assistant.

## Turn it on

1. Generate a token of at least 24 random characters. It must differ from `FRAME_TOKEN`.
2. Set `SLIDESHOW_TOKEN` in `.env`.
3. Restart the frame service: `docker compose up -d`.

If `SLIDESHOW_TOKEN` is empty, `/show` returns 404.

## Open it

The URL format is:

```
http://192.0.2.10:8099/show?key=SLIDESHOW_TOKEN&device=tablet
```

Replace the following:

- `SLIDESHOW_TOKEN`: your view-only token.
- `tablet`: a display name. Optional; the default is `default`.

Tap the right half of the screen for the next photo and the left half for the previous photo. The page keeps the key in the URL so that a kiosk reload works. A wrong key shows "Key not accepted". A small dot appears after five failed checks in a row.

To share state with a Home Assistant display, use the display's slug as `device`. Home Assistant creates the slug from the display name: `Living Room` becomes `living-room`. Allowed characters are `a-z`, `0-9`, `_` and `-`. The two then share the current photo and repeat history.

## Fully Kiosk Browser settings

1. Set **Start URL** to the slideshow URL.
2. Turn on **Keep Screen On**.
3. Optional: under **Device Management**, set a screen-off schedule for the night.

## What the view token can do

The view token can view photos, skip to the next photo, and go back. It cannot block, favorite or pick photos, change modes or settings, or reach other routes. The `/show` page accepts only `SLIDESHOW_TOKEN`, never `FRAME_TOKEN`. Frame Curator redacts keys from access logs.

The key sits in a URL, so it can end up in the kiosk browser's history. Treat it as view-only by design and never forward port 8099 to the internet.
