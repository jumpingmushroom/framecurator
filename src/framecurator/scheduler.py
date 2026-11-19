"""Always-on service: the hourly curator and the nightly backfill in slices, no external cron."""
import os
import time
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config
from .lock import Busy, job_lock

HEARTBEAT_EVERY = 600


def _u(d):
    """Aware datetimes sharing a tzinfo subtract as wall-clock; go through UTC for real durations."""
    return d.astimezone(UTC)


def _window_starts(now, sched):
    h, m = map(int, sched["backfill_start"].split(":"))
    for days in (-1, 0, 1):  # yesterday's may still be open, tomorrow's is the next one
        yield datetime.combine((now + timedelta(days=days)).date(), dtime(h, m), tzinfo=now.tzinfo)


def due(now, last_curator, rest_until, sched):
    """Decide the next job: ("curator", 0), ("backfill", hours) or ("sleep", seconds)."""
    step = timedelta(minutes=sched["curator_minutes"])
    if last_curator is None or _u(now) - _u(last_curator) >= step:
        return "curator", 0
    wake = [_u(last_curator) + step]
    if sched["backfill_hours"] > 0:
        for start in _window_starts(now, sched):
            end = start + timedelta(hours=sched["backfill_hours"])  # wall-clock arithmetic
            if _u(start) <= _u(now) < _u(end):
                if rest_until is None or _u(rest_until) <= _u(now):
                    left = min(_u(end), wake[0]) - _u(now)
                    if left >= timedelta(minutes=1):
                        return "backfill", left.total_seconds() / 3600
            elif _u(start) > _u(now):
                wake.append(_u(start))
                break
    if rest_until is not None and _u(rest_until) > _u(now):
        wake.append(_u(rest_until))
    return "sleep", min((min(wake) - _u(now)).total_seconds(), HEARTBEAT_EVERY)


def _window_end(now, sched):
    for start in _window_starts(now, sched):
        end = start + timedelta(hours=sched["backfill_hours"])
        if _u(start) <= _u(now) < _u(end):
            return end


def loop(cfg, clock, sleep, jobs, backfill_finished, passes=None):
    """Run due jobs forever (or `passes` times); a failing job is logged, never fatal."""
    sched, data_dir = cfg["schedule"], config.ROOT / cfg["data_dir"]
    now = clock()
    print(f"scheduler: curator every {sched['curator_minutes']} min; backfill from {sched['backfill_start']} "
          f"for {sched['backfill_hours']} h, zone {now.tzinfo}", flush=True)
    last, rest = None, None
    n = 0
    while passes is None or n < passes:
        n += 1
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "curator.heartbeat").touch()
        now = clock()
        kind, arg = due(now, last, rest, sched)
        if kind == "sleep":
            sleep(arg)
            continue
        next_curator = now if kind == "curator" else _u(last) + timedelta(minutes=sched["curator_minutes"])
        try:
            with job_lock(data_dir):
                if kind == "curator":
                    jobs["curator"]()
                    print(f"{now:%F %T} curator done", flush=True)
                else:
                    code = jobs["backfill"](arg)
                    print(f"{now:%F %T} backfill slice of {arg:.2f} h exit {code}", flush=True)
                    if code == 2:
                        rest = next_curator
                    elif backfill_finished():
                        rest = _window_end(now, sched)
        except Busy:
            print(f"{now:%F %T} {kind} skipped: another run holds the lock", flush=True)
            if kind == "backfill":
                rest = next_curator
        except Exception as e:  # noqa: BLE001  (the service must outlive any single job)
            print(f"{now:%F %T} {kind} failed: {e!r}", flush=True)
            if kind == "backfill":
                rest = next_curator
        if kind == "curator":
            last = now  # also after a failure, so a broken run is retried next interval, not in a hot loop


def _clock():
    name = os.environ.get("TZ") or "UTC"
    try:
        tz = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        print(f"unknown time zone {name!r}, using UTC", flush=True)
        tz = ZoneInfo("UTC")
    return lambda: datetime.now(tz)


def main():
    from . import backfill, curator
    from .immich import Immich
    from .store import Store

    cfg = config.load_config()
    Immich(cfg).check_version(log=lambda m: print(m, flush=True))
    db = config.ROOT / cfg["data_dir"] / "state.db"

    def finished():
        import json
        raw = Store(db).get("backfill")
        return bool(raw and json.loads(raw).get("finished"))

    loop(cfg, _clock(), time.sleep, {"curator": lambda: curator.run(True),
                                     "backfill": lambda h: backfill.run(h, 0, 0)}, finished)


if __name__ == "__main__":
    main()
