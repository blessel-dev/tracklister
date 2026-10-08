"""App-wide search budget with a fake clock."""
from __future__ import annotations

from tracklister.core.jsonio import read_json
from tracklister.engine.ratelimit import SearchBudget


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_budget_window(tmp_path):
    clk = Clock()
    p = tmp_path / "search-budget.json"
    b = SearchBudget(p, per_time=34, window_s=220, clock=clk)
    assert b.wait_time(20) == 0
    b.reserve(20)
    clk.t += 10
    assert b.wait_time(14) == 0
    b.reserve(14)
    assert b.wait_time(1) == 210          # the first 20 expire 220 s after t=1000
    clk.t += 210
    assert b.wait_time(20) == 0
    assert b.wait_time(21) == 10          # the other 14 expire at t=1230
    assert read_json(p)["schema"] == "tracklister.searchbudget/1"


def test_budget_is_shared_between_instances_and_caps_big_batches(tmp_path):
    clk = Clock()
    p = tmp_path / "b.json"
    a, c = SearchBudget(p, clock=clk), SearchBudget(p, clock=clk)
    a.reserve(30)
    assert c.wait_time(5) == 220
    assert SearchBudget(tmp_path / "empty.json", clock=clk).wait_time(500) == 0   # capped at per_time


def test_budget_survives_corrupt_file(tmp_path):
    p = tmp_path / "b.json"
    p.write_text("{no json", encoding="utf-8")
    b = SearchBudget(p, clock=Clock())
    assert b.wait_time(3) == 0
    b.reserve(3)
    assert len(read_json(p)["events"]) == 3
