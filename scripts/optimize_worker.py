"""
Run pocaduck's optimize_point_cloud.py with retries for flaky parquet reads.

On the cluster, reads from NFS intermittently hand DuckDB wrong bytes for
intact files ("TProtocolException: Invalid data", "No magic bytes found at end
of file"). pocaduck then skips the whole batch of labels and still exits 0.
This wrapper, without modifying pocaduck:

- disables DuckDB's external file cache, so one bad read is not reused,
- retries a statement that fails with one of these errors, and
- if the retries are exhausted, exits non-zero (raising a BaseException, which
  pocaduck's ``except Exception`` cannot swallow), so LSF marks the job failed.

For ``--action optimize --labels-file F`` it also skips the labels listed in
``exclude_labels.txt`` next to F (written by find_large_labels.py), which are
too large for pocaduck to hold in memory, and logs every skipped label.

Usage: python optimize_worker.py /path/to/optimize_point_cloud.py [pocaduck args...]
"""

import atexit
import importlib.util
import os
import sys
import tempfile
import time
import types

import duckdb

MAX_ATTEMPTS = 5
TRANSIENT_ERRORS = ("TProtocolException", "No magic bytes found")


class ReadFailed(BaseException):
    """Not an Exception subclass, so pocaduck's batch loop cannot swallow it."""


def _is_transient(e: Exception) -> bool:
    return any(s in str(e) for s in TRANSIENT_ERRORS)


def _retry(fn, what: str):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except duckdb.Error as e:
            if not _is_transient(e):
                raise
            if attempt == MAX_ATTEMPTS:
                raise ReadFailed(f"giving up after {MAX_ATTEMPTS} attempts: {e}") from e
            print(f"Retrying {what} ({attempt}/{MAX_ATTEMPTS - 1}) after: {e}"[:500],
                  file=sys.stderr, flush=True)
            time.sleep(2 ** attempt)


class _Result:
    """Result of an execute(); re-runs the statement if fetching fails."""

    def __init__(self, con, args):
        self._con, self._args = con, args

    def _fetch(self, method):
        state = {"first": True}

        def run():
            if not state["first"]:
                self._con.execute(*self._args)
            state["first"] = False
            return getattr(self._con, method)()

        return _retry(run, "query")

    def fetchall(self):
        return self._fetch("fetchall")

    def fetchone(self):
        return self._fetch("fetchone")

    def fetchdf(self):
        return self._fetch("fetchdf")

    def df(self):
        return self._fetch("fetchdf")


class _Connection:
    def __init__(self, con):
        self._con = con
        con.execute("SET enable_external_file_cache = false")

    def execute(self, *args):
        _retry(lambda: self._con.execute(*args), "query")
        return _Result(self._con, args)

    def __getattr__(self, name):
        return getattr(self._con, name)


EXCLUDE_FILE = "exclude_labels.txt"


def _exclude_labels(argv: list[str]) -> list[str]:
    """Return argv with --labels-file pointing to a copy without excluded labels."""
    if "optimize" not in argv or "--labels-file" not in argv:
        return argv
    i = argv.index("--labels-file") + 1
    exclude_path = os.path.join(os.path.dirname(argv[i]), EXCLUDE_FILE)
    if not os.path.exists(exclude_path):
        return argv

    with open(exclude_path) as f:
        rows = [line.split("\t") for line in f if line.strip() and not line.startswith("#")]
    points = {int(r[0]): r[1].strip() if len(r) > 1 else "?" for r in rows}
    with open(argv[i]) as f:
        labels = [line.strip() for line in f if line.strip()]
    skipped = [label for label in labels if int(label) in points]
    print(f"Skipping {len(skipped)} of {len(labels)} labels listed in {exclude_path}",
          flush=True)
    for label in skipped:
        print(f"Skipped label {label} ({points[int(label)]} points)", flush=True)
    if not skipped:
        return argv

    fd, filtered = tempfile.mkstemp(prefix="labels_", suffix=".txt")
    atexit.register(os.remove, filtered)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(label for label in labels if int(label) not in points))
    return argv[:i] + [filtered] + argv[i + 1:]


def main():
    optimizer, sys.argv = sys.argv[1], _exclude_labels(sys.argv[1:])
    spec = importlib.util.spec_from_file_location("optimize_point_cloud", optimizer)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # pocaduck calls duckdb.connect() through its module-level `duckdb` name.
    shim = types.ModuleType("duckdb")
    shim.__dict__.update(duckdb.__dict__)
    shim.connect = lambda *a, **kw: _Connection(duckdb.connect(*a, **kw))
    module.duckdb = shim
    module.main()


if __name__ == "__main__":
    main()
