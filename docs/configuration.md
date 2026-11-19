# Configuration

Frame Curator reads `config.yaml` (copy it from `config.example.yaml`) and environment variables from `.env`. Built-in defaults apply to every setting that you omit.

## Required settings

| Setting | Description |
|---|---|
| `immich.url` | Base URL of Immich, with no trailing slash. |
| `ollama.url` | Address of the Ollama host that runs the vision model. |
| `home.lat`, `home.lon` | Home coordinates. Alternatively, omit them and set `ha.url` plus the `HA_TOKEN` variable to read `zone.home` from Home Assistant. |

Frame Curator stores home coordinates only in this file. It never writes them to tags or logs.

## Settings with defaults

| Setting | Default | Change it when |
|---|---|---|
| `home.radius_m` | `300` | Photos taken within this many meters of home count as "at home". |
| `ollama.model` | `gemma3:4b` | You want a different Ollama vision model. |
| `ollama.min_score` | `6` | You want stricter (higher) or looser (lower) photo selection. Scores run from 1 to 10. |
| `travel_km` | `30` | Photos farther from home than this count as travel and pass. |
| `exclude_albums` | `[]` | You have albums whose photos must never appear. List the album names. |
| `picks_album` | `Frame - Picks` | You named your picks album differently. |
| `window_days` | `60` | You want the hourly curator to look further back. Older photos come from the backfill. |
| `data_dir` | `data` | You run without Docker and want state somewhere else. In Docker the data folder is the `./data:/app/data` mount: leave `data_dir` at its default. |
| `display.width`, `display.height` | `1920`, `1200` | Your default display has another resolution. Each Home Assistant display sets its own size. |
| `mix.on_this_day` | `0.30` | Share of memories from this day in past years. |
| `mix.favorites_picks` | `0.20` | Share of favorites and picks. |
| `mix.recent_30d` | `0.35` | Share of photos from the last 30 days. |
| `mix.library` | `0.15` | Share of the whole curated library. |
| `repeat_days` | `14` | A small pool repeats too soon. Lower it, or grow the pool. |
| `screenshot_name` | a regular expression | Your screenshots or downloads use other file names. |
| `ocr_keywords` | `receipt, invoice, subtotal, total, vat, order number, tracking` | You want to catch receipts in another language. Append words. Lists replace the default, so repeat the defaults you want to keep. |
| `frame.port` | `8099` | Port 8099 is taken. Also change the port mapping in `docker-compose.yml`. |
| `frame.rotate_minutes` | `15` | You want photos to change faster or slower. |
| `frame.image_size` | `preview` | Use `fullsize` for large screens. It needs the `asset.download` permission. |
| `frame.pool_ttl_minutes` | `5` | You want the API to refresh its photo list more or less often. |
| `schedule.curator_minutes` | `60` | You want the curator to run more or less often. |
| `schedule.backfill_start` | `"00:30"` | The GPU is busy then. Use `HH:MM`. |
| `schedule.backfill_hours` | `5.5` | You want a longer or shorter nightly window. Use 0 to 23.5. `0` turns the backfill off. |

Mix weights and the repeat window can also be changed per display in Home Assistant. The minimum score can also be changed there, and applies to all displays.

## Environment variables

| Variable | Description |
|---|---|
| `FRAME_TOKEN` | Required. Token for the frame API (at least 24 characters). |
| `IMMICH_FRAME_KEY` | Required. Immich key for the `frame` service. |
| `IMMICH_CURATOR_KEY` | Required. Immich key for the `curator` service. |
| `SLIDESHOW_TOKEN` | Optional. View-only token for the slideshow page (at least 24 characters, different from `FRAME_TOKEN`). Empty turns the slideshow off. See [Slideshow](slideshow.md). |
| `HA_TOKEN` | Optional. Home Assistant long-lived token. Needed only to read `zone.home`. |
| `TZ` | Time zone for the nightly backfill window, for example `Europe/Oslo`. Default `UTC`. Set it, or the window runs on UTC time. |
| `FRAMECURATOR_VERSION` | Optional. Pins the image tag, for example `0.1.0`. Default `latest`. |

## Data folder permissions

The container runs as UID 1000. The `data` folder must be writable by that user. On Unraid:

```sh
chown -R 1000:1000 /mnt/user/appdata/framecurator/data
```

Apply the same to `reports` if you use the sample report.

## Schedule

The `curator` service runs the curator every `schedule.curator_minutes`. During the nightly window it backfills older photos. On daylight-saving nights, the window still runs from `backfill_start` to the same local end time, so it is an hour longer or shorter in real time.
