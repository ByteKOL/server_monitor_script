# monitor.py
import os

import json
import psutil
import datetime
import pytz

from .logger_config import logger

try:
    from .. import config  # package mode
except Exception:
    import config  # direct/path mode
from .custom_exception import ClientException

class Monitor:
    """
    Monitor system stats every second and aggregate hourly data.
    CPU average per core, RAM average, bandwidth total, disk last.
    """

    def __init__(self):
        # Hourly aggregated values
        self.cpu_per_core_avg = []  # list per core
        self.cpu_total_avg = 0

        self.ram_avg = 0
        self.ram_min = float("inf")
        self.ram_max = 0

        self.bandwidth_total = 0.0

        self.disk_used = 0.0
        self.disk_total = 0.0  # GB
        self.sample_count = 0

        # For bandwidth calculation
        self.last_net = psutil.net_io_counters()

    def update_current_stats(self, current_stats):
        """
        Update hourly aggregated values based on current stats.
        current_stats: dict returned from get_current_stats()
        """
        cpu: list = current_stats["cpu"]  # list per core
        ram_used: float = current_stats["ram"]["used"]  # float GB

        # Update CPU average per core
        if not self.cpu_per_core_avg:
            self.cpu_per_core_avg = cpu.copy()
        else:
            # Incremental average: new_avg = (old_avg * n + new_val) / (n+1)
            self.cpu_per_core_avg = [(self.cpu_per_core_avg[i] * self.sample_count + cpu[i]) / (self.sample_count + 1)
                                     for i in range(len(cpu))]
        total_core = len(self.cpu_per_core_avg)
        self.cpu_total_avg = sum(self.cpu_per_core_avg) / total_core

        # Update RAM
        if not self.ram_avg:
            self.ram_avg = ram_used
        else:
            self.ram_avg = (self.ram_avg*self.sample_count + ram_used)/(self.sample_count+1)
        self.ram_min = min(self.ram_min, current_stats['ram']['used'])
        self.ram_max = max(self.ram_max, current_stats['ram']['used'])

        self.bandwidth_total += current_stats["bandwidth"]['transfer_total']
        self.disk_used = current_stats["disk"]["used"]
        self.disk_total = current_stats["disk"]["total"]
        self.sample_count += 1

    def get_and_update_current_stats(self):
        # can run per 1s
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()

        # Calculate bandwidth for this second
        bw_bytes = (net.bytes_sent - self.last_net.bytes_sent) + \
                   (net.bytes_recv - self.last_net.bytes_recv)
        bw_mb = bw_bytes / (1024 ** 2)
        self.last_net = net

        # Prepare snapshot for realtime
        snapshot = {
            "datetime": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "cpu": [round(c, 2) for c in psutil.cpu_percent(percpu=True)],
            "ram": {
                'total': round(ram.total / (1024**3), 2),
                'used': round((ram.total - ram.available) / (1024**3), 2),
                'unit': "GB",
            },
            "disk": {
                'total': round(disk.total / (1024**3), 2),
                'used': round(disk.used / (1024**3), 2),
                "unit": "GB",
            },
            "bandwidth": {"unit": "MB", "transfer_total": round(bw_mb, 2)},
        }
        self.update_current_stats(snapshot)
        return snapshot

    def get_and_reset_stats(self) -> dict:
        """
        Return hourly aggregated data and reset counters.
        """
        if self.sample_count == 0:
            return None
        res = {
            "datetime": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "cpu": {
                'cpu_per_core_avg': [round(c, 2) for c in self.cpu_per_core_avg],
                'cpu_total_avg': round(self.cpu_total_avg, 2),
            },
            "ram": {
                "unit": "GB",
                "min_used": round(self.ram_min, 2),
                "max_used": round(self.ram_max, 2),
                "avg_used": round(self.ram_avg, 2),
                "total": round(psutil.virtual_memory().total / (1024**3), 2)
            },
            "disk": {
                "unit": "GB",
                "used": round(self.disk_used, 2),
                "total": round(self.disk_total, 2)
            },
            "bandwidth": {"unit": "MB", "transfer_total": round(self.bandwidth_total, 2)}
        }
        # Reset counters
        self.cpu_per_core_avg = []
        self.cpu_total_avg = 0
        self.ram_avg = 0
        self.ram_min = float("inf")
        self.ram_max = 0
        self.bandwidth_total = 0.0
        self.disk_used = 0.0
        self.disk_total = 0.0
        self.sample_count = 0
        return res

    def push_to_file(self):
        current_stats_data = self.get_and_reset_stats()
        if not current_stats_data:
            return
        try:
            with open(config.json_file_path_1h, "r") as f:
                current_1h_file_data = json.load(f)
        except:
            current_1h_file_data = []

        if current_1h_file_data:
            last = current_1h_file_data[-1]
            # Convert datetime string to datetime object
            last_dt = datetime.datetime.fromisoformat(last["datetime"])
            new_dt = datetime.datetime.fromisoformat(current_stats_data["datetime"])
            # delta_sec = (new_dt - last_dt).total_seconds()

            if last_dt.hour == new_dt.hour and last_dt.date() == new_dt.date():
                merged_dt = last["datetime"]  # keep original datetime
                current_1h_file_data[-1] = self._merge_monitor_records([
                    current_1h_file_data[-1], current_stats_data
                ], merged_dt)
            else:
                current_1h_file_data.append(current_stats_data)
        else:
            current_1h_file_data.append(current_stats_data)

        # Write to file
        with open(config.json_file_path_1h, "w") as f:
            to_write = current_1h_file_data
            if len(current_1h_file_data) > config.max1h_record_length:
                to_write = current_1h_file_data[:config.max1h_record_length]
            json.dump(to_write, f)

        logger.info(f"Hourly data written to {config.json_file_path_1h}")
        self._push_to_file_1day()
        self._push_to_file_1month()

    def _merge_monitor_records(self, records, merged_dt: str):
        cpu_per_core_sum = [0.0] * len(records[0]["cpu"]["cpu_per_core_avg"])
        cpu_total_sum = 0.0

        ram_avg_sum = 0.0
        ram_min = float("inf")
        ram_max = float("-inf")

        bandwidth_total = 0.0
        disk_used_max = 0.0
        disk_total = records[0]["disk"]["total"]

        for r in records:
            for i, val in enumerate(r["cpu"]["cpu_per_core_avg"]):
                cpu_per_core_sum[i] += val
            cpu_total_sum += r["cpu"]["cpu_total_avg"]

            ram_avg_sum += r["ram"]["avg_used"]
            ram_min = min(ram_min, r["ram"]["min_used"])
            ram_max = max(ram_max, r["ram"]["max_used"])

            bandwidth_total += r["bandwidth"]["transfer_total"]
            disk_used_max = max(disk_used_max, r["disk"]["used"])

        n = len(records)
        merged = {
            "datetime": merged_dt,
            "cpu": {
                "cpu_per_core_avg": [round(avg_core / n, 2) for avg_core in cpu_per_core_sum],
                "cpu_total_avg": round(cpu_total_sum / n, 2),
            },
            "ram": {
                "unit": "GB",
                "avg_used": round(ram_avg_sum / n, 2),
                "min_used": round(ram_min, 2),
                "max_used": round(ram_max, 2),
                "total": records[0]["ram"]["total"],
            },
            "disk": {
                "unit": "GB",
                "used": round(disk_used_max, 2),
                "total": disk_total,
            },
            "bandwidth": {"unit": "MB", "transfer_total": round(bandwidth_total, 2)},
        }
        return merged

    def _push_to_file_1day(self):
        try:
            with open(config.json_file_path_1h, "r") as f:
                data_1h = json.load(f)
        except:
            return

        if not data_1h:
            return

        try:
            with open(config.json_file_path_1day, "r") as f:
                file_records_1d = json.load(f)
        except:
            file_records_1d = []

        grouped_hourly_record_by_same_date = {}
        for r in data_1h:
            dt = datetime.datetime.fromisoformat(r["datetime"])
            key = dt.date().strftime('%Y-%m-%d')
            grouped_hourly_record_by_same_date.setdefault(key, []).append(r)
        for r in file_records_1d:
            grouped_hourly_record_by_same_date.setdefault(r['datetime'], []).append(r)

        daily_records = []
        for recs in grouped_hourly_record_by_same_date.values():
            merged_dt = recs[0]["datetime"][:10] # YYYY-MM-DD
            merged = self._merge_monitor_records(recs, merged_dt)
            daily_records.append(merged)

        data_1d = sorted(daily_records, key=lambda r: r["datetime"])[-config.max1d_record_length:]
        with open(config.json_file_path_1day, "w") as f:
            json.dump(data_1d, f)
        logger.info(f"Daily data written to {config.json_file_path_1day}")

    def _push_to_file_1month(self):
        try:
            with open(config.json_file_path_1day, "r") as f:
                data_1day_list = json.load(f)
        except:
            return

        if not data_1day_list:
            return

        try:
            with open(config.json_file_path_1month, "r") as f:
                file_records_1month = json.load(f)
        except:
            file_records_1month = []

        grouped_daily_record_by_same_month = {}
        for r in data_1day_list:
            dt = datetime.datetime.fromisoformat(r["datetime"])
            key = dt.strftime('%Y-%m')
            grouped_daily_record_by_same_month.setdefault(key, []).append(r)
        for r in file_records_1month:
            grouped_daily_record_by_same_month.setdefault(r['datetime'], []).append(r)

        monthly_records = []
        for recs in grouped_daily_record_by_same_month.values():
            merged_dt = datetime.datetime.fromisoformat(recs[0]["datetime"]).strftime('%Y-%m')
            merged = self._merge_monitor_records(recs, merged_dt)
            monthly_records.append(merged)

        records_1month = sorted(monthly_records, key=lambda r: r["datetime"])[-config.max1month_record_length:]
        with open(config.json_file_path_1month, "w") as f:
            json.dump(records_1month, f)
        logger.info(f"Daily data written to {config.json_file_path_1month}")

    def _get_1h_monitor_records(self, client_time_zone: str, max_records: int):
        if not os.path.exists(config.json_file_path_1h):
            self.push_to_file()

        with open(config.json_file_path_1h, "r") as f:
            current_1h_file_data = json.load(f)

        records_1h = current_1h_file_data[-max_records:]
        try:
            client_tz = pytz.timezone(client_time_zone)
        except pytz.exceptions.UnknownTimeZoneError:
            raise ClientException(f"Invalid Timezone: {client_time_zone}")

        for record in records_1h:
            utc_time = datetime.datetime.fromisoformat(record['datetime'])
            record['datetime'] = utc_time.astimezone(client_tz).strftime('%m-%d %Hh')
        return records_1h

    def _get_1day_monitor_records(self, client_time_zone: str, max_records: int):
        if not os.path.exists(config.json_file_path_1day):
            raise ClientException("No Data")
        with open(config.json_file_path_1day, "r") as f:
            current_1h_file_data = json.load(f)

        records_1day = current_1h_file_data[-max_records:]
        try:
            client_tz = pytz.timezone(client_time_zone)
        except pytz.exceptions.UnknownTimeZoneError:
            raise ClientException(f"Invalid Timezone: {client_time_zone}")

        for record in records_1day:
            utc_time = datetime.datetime.fromisoformat(record['datetime'])
            record['datetime'] = utc_time.astimezone(client_tz).strftime('%Y-%m-%d')
        return records_1day

    def _get_1month_monitor_records(self, max_records: int):
        if not os.path.exists(config.json_file_path_1month):
            raise ClientException("No Data")
        with open(config.json_file_path_1month, 'r') as f:
            current_1month_file_data = json.load(f)
        return current_1month_file_data[-max_records:]

    def get_last_24h_monitor_data(self, client_time_zone: str):
        return self._get_1h_monitor_records(client_time_zone=client_time_zone, max_records=24)

    def get_last_7days_monitor_data(self, client_time_zone: str):
        return self._get_1day_monitor_records(client_time_zone=client_time_zone, max_records=7)

    def get_last_30days_monitor_data(self, client_time_zone: str):
        return self._get_1day_monitor_records(client_time_zone=client_time_zone, max_records=30)

    def get_last_12months_monitor_data(self):
        return self._get_1month_monitor_records(max_records=12)
