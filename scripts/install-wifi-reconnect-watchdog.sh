#!/bin/bash
set -euo pipefail
if [ "$EUID" -ne 0 ]; then
  echo "Run this installer with administrator privileges."
  exit 1
fi
task_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for target in /usr/local/lib/wifi-reconnect-watchdog.py /etc/systemd/system/wifi-reconnect-watchdog.service /etc/systemd/system/wifi-reconnect-watchdog.timer; do
  if [ -e "$target" ]; then
    echo "Already exists; refusing to overwrite: $target"
    exit 1
  fi
done
/usr/bin/python3 "$task_dir/wifi-reconnect-watchdog.py" --self-test
/usr/bin/python3 "$task_dir/wifi-reconnect-watchdog.py" --check
install -m 0644 "$task_dir/wifi-reconnect-watchdog.py" /usr/local/lib/wifi-reconnect-watchdog.py
install -m 0644 "$task_dir/wifi-reconnect-watchdog.service" /etc/systemd/system/wifi-reconnect-watchdog.service
install -m 0644 "$task_dir/wifi-reconnect-watchdog.timer" /etc/systemd/system/wifi-reconnect-watchdog.timer
systemctl daemon-reload
systemctl enable --now wifi-reconnect-watchdog.timer
systemctl status wifi-reconnect-watchdog.timer --no-pager
