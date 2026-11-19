import subprocess
import sys

import pytest

from framecurator import lock


def test_second_holder_is_turned_away(tmp_path):
    with lock.job_lock(tmp_path), pytest.raises(lock.Busy), lock.job_lock(tmp_path):
        pass


def test_lock_is_free_after_the_holder_exits(tmp_path):
    with lock.job_lock(tmp_path):
        pass
    with lock.job_lock(tmp_path):
        pass


def test_lock_left_by_a_dead_process_is_acquirable(tmp_path):
    code = f"import fcntl,os;f=open({str(tmp_path / 'curator.lock')!r},'w');fcntl.flock(f,fcntl.LOCK_EX);os._exit(0)"
    subprocess.run([sys.executable, "-c", code], check=True)
    with lock.job_lock(tmp_path):
        pass
