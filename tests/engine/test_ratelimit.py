"""App-wide search budget with a fake clock.

SPDX-License-Identifier: GPL-3.0-or-later
"""
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


def test_a_reservation_bigger_than_a_window_is_spread_like_the_engines_limiter(tmp_path):
    """1.0.1, R4: a --desperate pass of 10 rows reserves 70 searches. The engine makes 34, waits for its
    window to renew, makes 34 more, then 2 (RateLimitedSemaphore). The next process must wait for all of
    them, not only for the first window."""
    clk = Clock()
    p = tmp_path / "b.json"
    b = SearchBudget(p, per_time=34, window_s=220, clock=clk)
    b.reserve(70)
    ev = read_json(p)["events"]
    assert ev.count(1000.0) == 34 and ev.count(1220.0) == 34 and ev.count(1440.0) == 2
    other = SearchBudget(p, per_time=34, window_s=220, clock=clk)   # another window or process
    assert other.wait_time(1) == 440        # the second window's 34 leave at 1220 + 220
    clk.t = 1450.0                          # the engine is done; its last 2 searches were at 1440
    assert other.wait_time(32) == 0
    assert other.wait_time(34) == 210       # those 2 still count until 1660
    clk.t = 1660.0
    assert other.wait_time(34) == 0
    b.reserve(5)                            # old events are dropped when the file is written
    assert read_json(p)["events"] == [1660.0] * 5


def test_a_clock_that_went_back_never_blocks_for_long(tmp_path):
    p = tmp_path / "b.json"
    SearchBudget(p, clock=Clock(100000.0)).reserve(34)
    assert SearchBudget(p, clock=Clock(1000.0)).wait_time(34) == 0   # 'events' a day ahead are dropped


def test_zero_or_negative_per_time_never_divides_by_zero(tmp_path):
    p = tmp_path / "b.json"
    SearchBudget(p, per_time=0, clock=Clock()).reserve(3)
    assert len(read_json(p)["events"]) == 3
