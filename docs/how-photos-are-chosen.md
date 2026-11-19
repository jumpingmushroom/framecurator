# How photos are chosen

The curator tags each photo in Immich. Verdicts are tags, so you can see and change them in Immich. Scores and reasons stay in the local SQLite database.

## Tags and albums

- `frame/yes`: the curator keeps the photo.
- `frame/no`: the curator rejects the photo.
- `frame/block`: never show. Only you set it, with the **Never show this** button or by hand. The curator never adds, removes or overrides it.
- Album **Frame - Picks**: photos you chose. They are always eligible.

The curator never touches a photo that already has a verdict tag, so you can change tags by hand.

## Rules first

The curator checks each photo against these rules in order. The first match decides: a rejection is final, and a keep still goes to the vision model.

1. Hidden, archived, trashed or offline: rejected.
2. In an album listed in `exclude_albums`: rejected.
3. File name matches `screenshot_name`: rejected.
4. No camera make or model in EXIF: rejected. This drops forwarded images.
5. Has a named person: kept.
6. Favorite: kept.
7. In the picks album: kept.
8. OCR text matches `ocr_keywords`: rejected as a receipt or document.
9. Farther than `travel_km` from home: kept as travel.

Every photo that the rules do not reject goes to the vision model, so every photo needs Ollama.

## Vision model

Ollama classifies the photo as people, travel, landscape, event, pet, document, product, screenshot or other, and gives a score from 1 to 10. Document, product and screenshot are junk categories. The model rejects them even for named people and travel photos. Photos that a rule kept stay kept unless the model calls them junk. Photos that no rule decided are kept if the score reaches `ollama.min_score`.

## Mix and repeats

Each display draws from the curated pool in these shares by default: 30% on this day, 20% favorites and picks, 35% last 30 days, 15% whole library. No photo repeats on the same display within `repeat_days` (14 by default). You can change both per display.

## Backfill

The hourly curator judges the last `window_days` (60). The backfill judges older photos, newest first, during a nightly window. It tags only keepers `frame/yes`. Rejects are recorded in the database without a tag. It records progress as it goes, so you can stop and rerun it. Run a sample first:

```sh
docker compose run --rm curator python -m framecurator.backfill --sample 300
```

The sample writes `reports/backfill-sample.html` and changes nothing. To run a backfill by hand, use `--apply` instead of `--sample 300`. Add `--hours N` or `--limit N` to stop early.
