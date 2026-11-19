# Frame Curator

Frame Curator picks the best photos from your [Immich](https://immich.app) library for a wall-mounted photo frame. A curator job judges your photos and tags them in Immich. A small API serves the next photo, sized for your screen. You show it in Home Assistant or in any browser.

- Rules on photo metadata and a local vision model reject screenshots, receipts and product shots.
- Photos of named people, favorites, and photos from trips pass.
- Each display gets a mix of memories ("on this day"), favorites, recent photos, and the whole library, without repeats.
- Portraits get a blurred background instead of a crop. Landscape crops follow faces.
- Everything stays on your network. No photo goes to a cloud service.

## Requirements

- Immich. Frame Curator is tested with v3.1.0. Other versions work with a warning in the log.
- Docker with Docker Compose.
- [Ollama](https://ollama.com) with the vision model pulled: `ollama pull gemma3:4b`. A GPU is recommended: judging takes about 1 s per photo on an RTX 3060 Ti.
- Optional: Home Assistant. Without it, use the [slideshow page](docs/slideshow.md).

## Quick start

1. Create two Immich API keys and the picks album. For the steps, see [Immich API keys](docs/immich-keys.md).
2. Copy the template files:

   ```sh
   cp .env.example .env
   cp config.example.yaml config.yaml
   ```

3. Edit `.env`. Set `FRAME_TOKEN` (at least 24 random characters, for example from `openssl rand -hex 24`; `SLIDESHOW_TOKEN` too, if you use it, and it must differ), `IMMICH_FRAME_KEY` and `IMMICH_CURATOR_KEY`.
4. Edit `config.yaml`. Set the Immich URL, the Ollama URL, and your home coordinates. For all settings, see [Configuration](docs/configuration.md).
5. Make the data folder writable by the container user (UID 1000):

   ```sh
   mkdir -p data reports && chown -R 1000:1000 data reports
   ```

6. Set `schedule.backfill_hours: 0` in `config.yaml` until you have reviewed the sample in step 8. Then start both services:

   ```sh
   docker compose up -d
   ```

   The `frame` service serves photos on port 8099. The `curator` service tags new photos every hour and backfills older photos each night.
7. Check what the backfill would do. This changes nothing and writes `reports/backfill-sample.html`:

   ```sh
   docker compose run --rm curator python -m framecurator.backfill --sample 300
   ```

8. Review the report. If you are happy, set `schedule.backfill_hours` back to `5.5` and run `docker compose restart curator`.
9. Show photos. See [Home Assistant](docs/home-assistant.md) or [Slideshow](docs/slideshow.md).

The API port (8099) must stay on your LAN. Never forward it on your router.

## Documentation

- [Configuration](docs/configuration.md): every setting and when to change it.
- [Immich API keys](docs/immich-keys.md): the two keys and their permissions.
- [Home Assistant](docs/home-assistant.md): install, entities, card and automation examples.
- [Slideshow](docs/slideshow.md): show photos on a tablet or any browser.
- [How photos are chosen](docs/how-photos-are-chosen.md): rules, vision model, tags and mix.
- [Troubleshooting](docs/troubleshooting.md): common problems and how to read the logs.
- [Threat model](docs/threat-model.md) and [security policy](SECURITY.md).
- [Changelog](CHANGELOG.md).

## Develop

```sh
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

The Home Assistant integration tests need `pip install pytest-homeassistant-custom-component`, then `cd tests_ha && pytest`.

## License

[MIT](LICENSE)
