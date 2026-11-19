# Threat model

## Assets worth protecting

1. Personal photos and their metadata (faces, names, places, dates).
2. Immich API keys.
3. Home Assistant long-lived token (read-only use: `zone.home`, presence).
4. Home location (config only).

## Trust boundaries

- Immich <-> framecurator (LAN, HTTP/HTTPS, `x-api-key`).
- framecurator <-> Home Assistant (LAN; HA fetches images, calls the Skip/Never-show actions).
- framecurator <-> Ollama (LAN, optional, photo previews sent to it; stays local).
- Anything else on the LAN reaching the frame API.

## Controls

| Risk | Control |
|---|---|
| Leaked Immich key gives broad library access | Two keys. **Curator**: `asset.read`, `tag.read`, `tag.create`, `tag.asset`, `album.read`, `person.read`, `face.read`, `asset.view`. **Frame**: `asset.read`, `asset.view`, `album.read`, `person.read`, `face.read`, `tag.read`, `tag.create`, `tag.asset` (Never show and Undo), `asset.update` (Favorite), `albumAsset.create` and `albumAsset.delete` (Pick), plus `asset.download` only with `image_size: fullsize`. Scope names confirmed against the live v3.1.0 spec. No admin scopes, and no `album.create`: the picks album is created by hand. |
| Frame key can edit photos (`asset.update` also covers dates, GPS, rating, description) | The frame API never accepts an asset id from a client and only ever sends `isFavorite`, for the photo currently on the requesting display. Picks only touch the configured picks album. A leaked frame token cannot reach arbitrary photos; a leaked Immich key can, so keep both secret. |
| Any LAN device pulls photos from the frame API | Bearer token required on every route except `/healthz`; constant-time compare; token in env, not in config file. Bind to the LAN interface only; never port-forward; do not put behind a public reverse proxy. |
| Slideshow token in a URL | The `SLIDESHOW_TOKEN` sits in the kiosk browser's URL and history. It is view-only by design: it can view, skip and go back, and `/show` never accepts `FRAME_TOKEN`. Keys are redacted from access logs. A leaked view token shows photos but cannot edit anything; rotate it by changing `SLIDESHOW_TOKEN`. A view-token holder can also create device names up to the display limit (16), which could block new displays; this is a LAN-only nuisance. |
| Token or key in logs, git or images | Redact in logs; `.env` and `config.yaml` gitignored; no secrets in the image; secrets via env or Docker secrets. |
| Frame API used to reach arbitrary Immich assets (IDOR) | Only serve assets that carry a curated tag or are in the picks album; reject any other id. |
| "Never show" abuse | Only adds `frame/block` to the photo on the requesting display. Undo removes only a block that display made through the API; other blocks are undone by hand in Immich. |
| Container compromise | Non-root user, read-only root filesystem, writable volume for SQLite only, no extra capabilities. |
| Immich reached over a public hostname | If Immich is only reachable through a public hostname, use HTTPS: the key and thumbnails cross the public internet in transit. Prefer a LAN address for `immich.url` to keep traffic internal. |
| Cloud leakage | No cloud APIs; Ollama is local; no telemetry; outbound traffic limited to Immich, HA and Ollama (a firewall rule on your router or host is recommended). |
| Home location exposure | Coordinates only in config and read from HA `zone.home`; never written to tags, logs or HTML reports. |
| Dry-run report exposure | The HTML report embeds personal thumbnails: generate to a local gitignored directory, never serve it publicly, delete when finished. |

## Out of scope

Compromised Immich or HA hosts, physical access to the wall panel.
