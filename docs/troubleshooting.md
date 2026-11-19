# Troubleshooting

## Read the logs

```sh
docker compose logs frame curator
docker compose logs -f curator
```

Run these in the folder that has `docker-compose.yml`. The second command follows the curator log live. The curator log shows each run, backfill slice and exit code. The access log shows redacted keys as `key=***`.

## The slideshow page stays on "no curated photos yet"

The page shows the server's message, "no curated photos yet": the curator has not tagged any photos yet. The first run starts when the `curator` service starts and can take a while. Watch `docker compose logs -f curator`. The page keeps retrying and shows the first photo by itself.

## "On this day" shows nothing

The backfill works newest first. Until it reaches past years, there are no memories. Check progress in the curator log.

## Photos repeat

The pool is small. Lower `repeat_days`, wait for the backfill to widen the pool, or loosen `ollama.min_score`.

## A tag changed back

Immich can write an older tag state back when a photo's tags change twice within a few seconds. Change a tag once, wait, and check it again.

## A photo was rejected for no camera

Photos without camera make or model in EXIF are rejected. Forwarded and downloaded images usually have none. Add such a photo to the picks album, or tag it `frame/yes`, to keep it.

## One day floods "on this day"

Scans with a wrong date can share a single date. Fix the date in Immich, or tag the photos `frame/no`.

## Permission denied on the data folder

The container runs as UID 1000. Run `chown -R 1000:1000 data reports` on the folders. See [Configuration](configuration.md).

## "already running" and exit code 3

A manual `--apply` prints "already running" and exits with 3 while the curator service holds the lock. Wait for the current job, then run it again. Exit code 2 means Ollama or Immich stopped answering.

## "Immich ... has not been tested"

The log shows this when your Immich version is not v3.1.0. Frame Curator can still work. Check that tags and photos appear as expected, and report problems.

## The slideshow shows "Key not accepted"

The `key` in the URL does not match `SLIDESHOW_TOKEN`. See [Slideshow](slideshow.md).
