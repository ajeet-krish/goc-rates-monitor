"""Phase 8.2 wait_for_print poll tests: extracted heredoc logic with mocked Valet.

The daily workflow polls Valet for the benchmark print before snapshotting.
The loop cannot run in CI locally, so these tests extract the quoted heredoc
Python from .github/workflows/daily.yml, compile it, and execute it in
process with fetch_valet_group, BaseClient, and load_benchmark_map mocked.
A missing tenor, a null value, or a fetch failure must exit nonzero, all
tenors observed must pass, and the weekday cron plus the 300 second interval
and 2700 second deadline stay pinned.
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "daily.yml"
TARGET_DATE = "2026-11-04"
POLL_GROUP = "TEST.VALET.GROUP"
POLL_INTERVAL_SECONDS = 300  # unit: seconds, sleep between poll attempts
POLL_DEADLINE_SECONDS = 2700  # unit: seconds, hard stop for the poll step
POLL_CRON = "30 16 * * 1-5"
TENORS = ("2Y", "5Y", "10Y", "30Y")
SERIES_IDS = (
    "BD.CDN.2YR.DQ.YLD",
    "BD.CDN.5YR.DQ.YLD",
    "BD.CDN.10YR.DQ.YLD",
    "BD.CDN.LONG.DQ.YLD",
)


def _workflow() -> dict[str, Any]:
    """Parse the daily workflow YAML as a mapping."""
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "daily.yml must parse to a mapping"
    return loaded


def _poll_run() -> str:
    """Return the run block of the single wait_for_print step."""
    steps = _workflow()["jobs"]["snapshot"]["steps"]
    matched = [step for step in steps if step.get("id") == "wait_for_print"]
    assert len(matched) == 1, "daily.yml must keep exactly one wait_for_print step"
    run = matched[0].get("run")
    assert isinstance(run, str), "wait_for_print must carry a run block"
    return run


def _poll_script() -> str:
    """Extract the quoted heredoc Python from the poll step and compile it."""
    run = _poll_run()
    assert "<<'PY'" in run, "the heredoc must stay quoted so the shell cannot expand it"
    lines = run.splitlines()
    starts = [index for index, line in enumerate(lines) if "<<'PY'" in line]
    assert len(starts) == 1, "wait_for_print must hold exactly one python heredoc"
    start = starts[0]
    ends = [index for index in range(start + 1, len(lines)) if lines[index].strip() == "PY"]
    assert ends, "the heredoc must close with a PY terminator"
    body = "\n".join(lines[start + 1 : ends[0]])
    compile(body, "wait_for_print heredoc", "exec")
    return body


def _observation(date_text: str, series_id: str, quality: str, value: Any) -> SimpleNamespace:
    """Build one Valet row shaped like the real observation object."""
    return SimpleNamespace(
        observation_date=date_text,
        quantity={"quality": quality, "value": value},
    )


def _benchmark_map() -> SimpleNamespace:
    """Build the four tenor benchmark map the poll loop iterates."""
    return SimpleNamespace(
        benchmarks={
            tenor: SimpleNamespace(valet_series_id=series_id)
            for tenor, series_id in zip(TENORS, SERIES_IDS, strict=True)
        }
    )


def _fetch_returning(groups: dict[str, list[SimpleNamespace]], calls: list[dict[str, Any]]) -> Any:
    """Return a fetch_valet_group stand in that records its keyword arguments."""

    def fetch(group: str, client: Any, **kwargs: Any) -> dict[str, list[SimpleNamespace]]:
        calls.append({"group": group, **kwargs})
        return groups

    return fetch


def _run_poll(script: str, monkeypatch: Any, fetch: Any) -> tuple[int, str, str]:
    """Execute the extracted poll script with mocked modules, returning its exit."""
    fake_base = types.ModuleType("goc_rates.clients.base")

    class _Client:
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *exc: Any) -> bool:
            return False

    fake_base.BaseClient = _Client
    fake_valet = types.ModuleType("goc_rates.clients.valet")
    fake_valet.VALET_GROUP = POLL_GROUP
    fake_valet.fetch_valet_group = fetch
    fake_config = types.ModuleType("goc_rates.config")

    def load_map(_path: str) -> SimpleNamespace:
        return _benchmark_map()

    fake_config.load_benchmark_map = load_map
    monkeypatch.setitem(sys.modules, "goc_rates.clients.base", fake_base)
    monkeypatch.setitem(sys.modules, "goc_rates.clients.valet", fake_valet)
    monkeypatch.setitem(sys.modules, "goc_rates.config", fake_config)
    monkeypatch.setenv("SNAPSHOT_DATE", TARGET_DATE)
    stdout = io.StringIO()
    stderr = io.StringIO()
    exit_code = 0
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            exec(compile(script, "wait_for_print heredoc", "exec"), {"__name__": "__poll__"})
        except SystemExit as exc:
            code = exc.code
            exit_code = code if isinstance(code, int) else 1
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_poll_step_parses_with_one_quoted_heredoc() -> None:
    """The workflow parses and the poll step carries one compilable heredoc."""
    script = _poll_script()
    assert "fetch_valet_group" in script
    assert 'os.environ["SNAPSHOT_DATE"]' in script


def test_poll_constants_and_weekday_cron_are_sane() -> None:
    """The cron pins weekday 16:30 UTC and the poll keeps 300 over 2700 seconds."""
    match = re.search(r'-\s*cron:\s*"([^"]+)"', WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert match is not None, "daily.yml must schedule with a quoted cron line"
    assert match.group(1) == POLL_CRON
    run = _poll_run()
    assert f"POLL_INTERVAL_SECONDS={POLL_INTERVAL_SECONDS}" in run
    assert f"POLL_DEADLINE_SECONDS={POLL_DEADLINE_SECONDS}" in run
    assert 'sleep "$POLL_INTERVAL_SECONDS"' in run
    assert "not yet published after the 45 minute poll window" in run
    assert POLL_DEADLINE_SECONDS % POLL_INTERVAL_SECONDS == 0
    assert POLL_DEADLINE_SECONDS >= POLL_INTERVAL_SECONDS * 4, "at least five attempts"
    assert POLL_DEADLINE_SECONDS <= 3600, "the poll must stop well inside the job limit"


def test_all_tenors_observed_exits_zero(monkeypatch: Any) -> None:
    """Every tenor observed on the target date passes the poll check."""
    script = _poll_script()
    calls: list[dict[str, Any]] = []
    groups = {
        series_id: [_observation(TARGET_DATE, series_id, "observed", 3.5)]
        for series_id in SERIES_IDS
    }
    code, out, err = _run_poll(script, monkeypatch, _fetch_returning(groups, calls))
    assert code == 0, out + err
    assert out.strip() == f"complete print for {TARGET_DATE} observed for all tenors"
    assert err == ""
    assert len(calls) == 1
    assert calls[0]["group"] == POLL_GROUP
    assert calls[0]["start_date"] == TARGET_DATE
    assert calls[0]["end_date"] == TARGET_DATE


def test_missing_tenor_exits_nonzero(monkeypatch: Any) -> None:
    """One tenor without a print fails the attempt with the tenor named."""
    script = _poll_script()
    groups = {
        series_id: [_observation(TARGET_DATE, series_id, "observed", 3.5)]
        for series_id in SERIES_IDS[:-1]
    }
    code, out, _err = _run_poll(script, monkeypatch, _fetch_returning(groups, []))
    assert code == 1
    assert f"incomplete print for {TARGET_DATE}" in out
    assert f"30Y: no observation for {TARGET_DATE}" in out


def test_null_value_tenor_exits_nonzero(monkeypatch: Any) -> None:
    """A tenor present but not observed fails with the value not observed detail."""
    script = _poll_script()
    groups = {
        series_id: [_observation(TARGET_DATE, series_id, "missing", None)]
        for series_id in SERIES_IDS
    }
    code, out, _err = _run_poll(script, monkeypatch, _fetch_returning(groups, []))
    assert code == 1
    assert f"incomplete print for {TARGET_DATE}" in out
    assert out.count("value not observed") == len(TENORS)


def test_fetch_failure_exits_nonzero(monkeypatch: Any) -> None:
    """A raising Valet fetch fails the attempt with a redacted poll message."""
    script = _poll_script()

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("upstream down")

    code, _out, err = _run_poll(script, monkeypatch, boom)
    assert code == 1
    assert "valet poll attempt failed: upstream down" in err
