import json
import os
import datetime

import pytest

from ..scripts.monitor import Monitor

try:
    from .. import config  # package mode
except Exception:
    import config  # direct/path mode


def write_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)


def read_json(path):
    with open(path, "r") as f:
        return json.load(f)


@pytest.fixture()
def temp_config(tmp_path, monkeypatch):
    data_dir = tmp_path
    json_1h = data_dir / "monitor_1h.json"
    json_1d = data_dir / "monitor_1day.json"

    monkeypatch.setattr(config, "json_file_path_1h", str(json_1h), raising=False)
    monkeypatch.setattr(config, "json_file_path_1day", str(json_1d), raising=False)
    monkeypatch.setattr(config, "max1d_record_length", 2, raising=False)

    return {
        "json_1h": str(json_1h),
        "json_1d": str(json_1d),
    }


def make_hourly_record(dt: datetime.datetime, cpu_total=10.0, ram_avg=1.0, bw=5.0, disk_used=20.0):
    ncores = 2
    return {
        "datetime": dt.isoformat(),
        "cpu": {
            "cpu_per_core_avg": [cpu_total] * ncores,
            "cpu_total_avg": cpu_total,
        },
        "ram": {
            "unit": "GB",
            "avg_used": ram_avg,
            "min_used": ram_avg,
            "max_used": ram_avg,
            "total": 32.0,
        },
        "disk": {
            "unit": "GB",
            "used": disk_used,
            "total": 100.0,
        },
        "bandwidth": {"unit": "MB", "transfer_total": bw},
    }


def test_push_to_file_1day_aggregates_and_trims(temp_config):
    # Prepare 1h data across 3 different days with varying values
    base = datetime.datetime(2025, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
    day1 = [make_hourly_record(base + datetime.timedelta(hours=i), cpu_total=10 + i, ram_avg=1 + i * 0.1, bw=5 + i,
                               disk_used=20 + i) for i in range(24)]
    day2 = [
        make_hourly_record(base + datetime.timedelta(days=1, hours=i), cpu_total=30 + i, ram_avg=2 + i * 0.1, bw=3 + i,
                           disk_used=22 + i) for i in range(24)]
    day3 = [
        make_hourly_record(base + datetime.timedelta(days=2, hours=i), cpu_total=50 + i, ram_avg=3 + i * 0.1, bw=1 + i,
                           disk_used=24 + i) for i in range(24)]

    all_hours = day1 + day2 + day3
    write_json(config.json_file_path_1h, all_hours)

    monitor = Monitor()
    monitor._push_to_file_1day()

    # Read daily
    days = read_json(config.json_file_path_1day)
    # max1d_record_length set to 2 -> only last 2 days remain
    assert len(days) == 2
    assert days[0]["datetime"] == "2025-01-02"
    assert days[1]["datetime"] == "2025-01-03"

    d2 = days[0]
    d3 = days[1]

    # Verify aggregation roughly matches (averages and sums)
    # day2 cpu_total_avg should be average of 24 values from 30..53 -> (30+53)/2 = 41.5
    assert d2["cpu"]["cpu_total_avg"] == pytest.approx(41.5, rel=0, abs=0.01)
    # day3 cpu_total_avg -> (50+73)/2 = 61.5
    assert d3["cpu"]["cpu_total_avg"] == pytest.approx(61.5, rel=0, abs=0.01)

    # RAM avg_used is average of 24 values forming arithmetic progression starting at 2.0, step 0.1 -> mean ~ 3.15
    assert d2["ram"]["avg_used"] == pytest.approx(3.15, rel=0, abs=0.01)
    # day3 start 3.0, step 0.1 -> mean ~ 4.15
    assert d3["ram"]["avg_used"] == pytest.approx(4.15, rel=0, abs=0.01)

    # Bandwidth should be sum over the day; for day2 values 3..26 -> sum = (3+26)*24/2 = 348
    assert d2["bandwidth"]["transfer_total"] == pytest.approx(348, rel=0, abs=0.01)
    # day3 values 1..24 -> sum = (1+24)*24/2 = 300
    assert d3["bandwidth"]["transfer_total"] == pytest.approx(300, rel=0, abs=0.01)

    # Disk used is max over the day; day2 max 22..45 -> 45; day3 max 24..47 -> 47
    assert d2["disk"]["used"] == pytest.approx(45.0, rel=0, abs=0.01)
    assert d3["disk"]["used"] == pytest.approx(47.0, rel=0, abs=0.01)
