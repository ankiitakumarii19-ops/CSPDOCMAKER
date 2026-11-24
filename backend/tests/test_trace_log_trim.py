"""The trace log is trimmed (No. 199, Stage 0): it used to grow forever on
the server; now it rotates like app.jsonl and keeps a fixed number of old
files."""

import json

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from app.telemetry import JsonlSpanExporter


def _write_spans(exporter, n):
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    for i in range(n):
        with tracer.start_as_current_span(f"span-{i}"):
            pass


def test_a_full_trace_log_rotates_and_old_files_are_dropped(tmp_path):
    path = tmp_path / "traces.jsonl"
    exporter = JsonlSpanExporter(str(path), max_bytes=500, backup_count=3)
    _write_spans(exporter, 60)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["traces.jsonl", "traces.jsonl.1", "traces.jsonl.2",
                     "traces.jsonl.3"], files
    # Every file is still whole JSON lines, and none is far past the limit.
    for p in tmp_path.iterdir():
        lines = p.read_text(encoding="utf-8").splitlines()
        assert lines and all(json.loads(line)["type"] == "span" for line in lines)
        assert p.stat().st_size < 500 + 2000


def test_a_small_trace_log_is_left_alone(tmp_path):
    path = tmp_path / "traces.jsonl"
    _write_spans(JsonlSpanExporter(str(path)), 5)
    assert [p.name for p in tmp_path.iterdir()] == ["traces.jsonl"]
    assert len(path.read_text(encoding="utf-8").splitlines()) == 5
