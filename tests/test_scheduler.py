import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from framecurator import lock, scheduler
from framecurator.scheduler import due, loop

TZ = ZoneInfo("Europe/Oslo")
S = {"curator_minutes": 60, "backfill_start": "00:30", "backfill_hours": 5.5}


def at(s):
    return datetime.fromisoformat(s).replace(tzinfo=TZ)


def test_first_pass_runs_the_curator_even_inside_the_window():
    assert due(at("2026-11-20 02:00"), None, None, S) == ("curator", 0)


def test_backfill_slice_ends_at_the_next_curator_run():
    assert due(at("2026-11-20 01:10"), at("2026-11-20 01:00"), None, S) == ("backfill", pytest.approx(50 / 60))


def test_last_slice_ends_with_the_window():
    assert due(at("2026-11-20 05:50"), at("2026-11-20 05:30"), None, S) == ("backfill", pytest.approx(10 / 60))


def test_window_crossing_midnight():
    s = S | {"backfill_start": "23:00", "backfill_hours": 3}
    assert due(at("2026-11-21 01:00"), at("2026-11-21 00:30"), None, s)[0] == "backfill"


def test_backfill_off_and_resting_backfill_sleep():
    assert due(at("2026-11-20 01:10"), at("2026-11-20 01:00"), None, S | {"backfill_hours": 0})[0] == "sleep"
    assert due(at("2026-11-20 01:10"), at("2026-11-20 01:00"), at("2026-11-20 06:00"), S)[0] == "sleep"


def test_sleep_is_capped_for_the_heartbeat():
    assert due(at("2026-11-20 12:01"), at("2026-11-20 12:00"), None, S) == ("sleep", 600)


def test_window_on_dst_change_nights_still_starts_at_0030_local():
    for day in ("2026-10-25", "2027-03-28"):
        assert due(at(f"{day} 00:29"), at(f"{day} 00:20"), None, S)[0] == "sleep"
        assert due(at(f"{day} 00:31"), at(f"{day} 00:20"), None, S)[0] == "backfill"


def test_curator_interval_counts_real_time_across_dst():
    # 01:30 CEST -> 02:30 CET is two real hours; a naive wall-clock diff would say one
    assert due(at("2026-10-25 02:30").replace(fold=1), at("2026-10-25 01:30"), None, S | {"backfill_hours": 0})[0] == "curator"


class Env:
    """Fake clock: sleeping advances it; jobs are recorded."""

    def __init__(self, start, tmp_path, behaviour=None):
        self.now, self.calls, self.behaviour, self.finished = start, [], behaviour or {}, False
        self.cfg = {"data_dir": str(tmp_path), "schedule": S}
        self.tmp = tmp_path

    def job(self, name):
        def run(*a):
            self.calls.append((name, self.now))
            b = self.behaviour.get(name)
            if isinstance(b, Exception):
                raise b
            return b if name == "backfill" else None
        return run

    def sleep(self, secs):
        self.now += timedelta(seconds=secs)

    def go(self, passes):
        loop(self.cfg, clock=lambda: self.now, sleep=self.sleep, passes=passes,
             jobs={"curator": self.job("curator"), "backfill": self.job("backfill")},
             backfill_finished=lambda: self.finished)


def test_a_failing_job_does_not_stop_the_loop(tmp_path, capsys):
    e = Env(at("2026-11-20 12:00"), tmp_path, {"curator": RuntimeError("boom")})
    e.go(3)
    assert [c[0] for c in e.calls] == ["curator"]
    assert "boom" in capsys.readouterr().out


def test_backfill_exit_2_rests_until_the_next_curator_run(tmp_path):
    e = Env(at("2026-11-20 01:00"), tmp_path, {"backfill": 2})
    e.go(6)
    assert [c[0] for c in e.calls] == ["curator", "backfill"]  # not retried within the hour


def test_finished_backfill_rests_until_the_window_ends(tmp_path):
    e = Env(at("2026-11-20 01:00"), tmp_path, {"backfill": 0})
    e.finished = True
    e.go(12)
    assert [c[0] for c in e.calls].count("backfill") == 1


def test_busy_is_logged_and_skipped(tmp_path, capsys):
    e = Env(at("2026-11-20 12:00"), tmp_path, {"curator": lock.Busy("x")})
    e.go(1)
    assert "skipped: another run holds the lock" in capsys.readouterr().out


def test_heartbeat_is_touched_every_pass(tmp_path):
    e = Env(at("2026-11-20 12:00"), tmp_path)
    e.go(1)
    hb = tmp_path / "curator.heartbeat"
    os.utime(hb, (1, 1))
    e.go(1)
    assert hb.stat().st_mtime > 1000


@pytest.mark.parametrize("tz", ["Nowhere/Land", "/etc/localtime"])
def test_bad_tz_falls_back_to_utc_with_a_warning(monkeypatch, capsys, tz):
    monkeypatch.setenv("TZ", tz)
    assert scheduler._clock()().utcoffset().total_seconds() == 0
    assert "using UTC" in capsys.readouterr().out
