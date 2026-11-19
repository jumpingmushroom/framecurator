# Changelog

## [0.1.0] - 2026-11-19

- Curator: tags Immich photos `frame/yes` or `frame/no` from metadata rules and a local Ollama vision model.
- Backfill: judges older photos newest first in a nightly window, resumable, with a sample report.
- Frame API: serves the next photo sized for each display, with mix, repeat window and filter modes.
- Home Assistant integration: image entity, sensors, buttons, switches and selects per display.
- Slideshow: a view-only browser page for tablets without Home Assistant.
- Curator service: runs the hourly curator and the nightly backfill from one container image.
