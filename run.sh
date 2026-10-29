#!/usr/bin/env bash
# สคริปต์รันเซิร์ฟเวอร์ NVR Viewer
set -e
cd "$(dirname "$0")"

# สร้าง virtualenv ครั้งแรก
if [ ! -d ".venv" ]; then
  echo "==> สร้าง virtualenv และติดตั้ง dependencies..."
  python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -q -r requirements.txt
fi

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-2318}"

echo "==> เปิดที่ http://$(hostname -I | awk '{print $1}'):${PORT}  (เครื่องอื่นในวงแลนเข้าได้)"
exec .venv/bin/uvicorn app:app --host "$HOST" --port "$PORT"
