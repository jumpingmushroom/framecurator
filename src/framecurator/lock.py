"""One curator or backfill run at a time: an flock the OS drops if the process dies."""
import fcntl
from contextlib import contextmanager
from pathlib import Path


class Busy(Exception):
    pass


@contextmanager
def job_lock(data_dir: Path):
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / "curator.lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Busy("already running") from None
        yield
