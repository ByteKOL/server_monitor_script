# config.py
import os
_current_dir = os.path.dirname(os.path.abspath(__file__))

datadir = os.path.join(_current_dir, "data")
http_port = 22111

import os
os.makedirs(datadir, exist_ok=True)

max1h_record_length = 168 # 7 * 24 (7days)
json_file_path_1h = os.path.join(datadir, "monitor_1h.json")
json_file_path_1day = os.path.join(datadir, "monitor_1day.json")
json_file_path_1month = os.path.join(datadir, "monitor_1month.json")
# json_file_path_6_months = os.path.join(datadir, "monitor_6_months.json")

logfile = os.path.join(datadir, "monitor.log")
max1d_record_length = 30  # keep last 30 days
max1month_record_length = 12
