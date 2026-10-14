#!/usr/bin/env bash
# ExpoPulse one-command demo runner (macOS / Bash 3.2+).
# Usage: ./run_simulation.sh crowd|restricted|fall|equipment
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
MODE="${1:-}"
case "$MODE" in
  crowd|restricted|fall|equipment) ;;
  *) echo "Usage: ./run_simulation.sh {crowd|restricted|fall|equipment}" >&2; exit 2 ;;
esac

VENV_PY="$ROOT/venv/bin/python"
[[ -x "$VENV_PY" ]] || { echo "Missing venv/bin/python. Create the project virtual environment first." >&2; exit 1; }
[[ -f "$ROOT/manage.py" ]] || { echo "Run this script from the ExpoPulse repository." >&2; exit 1; }
if [[ "$MODE" != equipment ]]; then
  command -v ffmpeg >/dev/null || { echo "Missing FFmpeg (brew install ffmpeg)." >&2; exit 1; }
fi
command -v curl >/dev/null || { echo "Missing curl." >&2; exit 1; }
command -v lsof >/dev/null || { echo "Missing lsof." >&2; exit 1; }

OWNED_PIDS=()
STREAM_DIR=""
cleanup() {
  trap - EXIT INT TERM
  echo
  echo "Stopping processes started by this runner..."
  for pid in "${OWNED_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  for pid in "${OWNED_PIDS[@]}"; do wait "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN 2>/dev/null | grep -q LISTEN; }
start_bg() {
  "$@" &
  OWNED_PIDS+=("$!")
}
wait_http() {
  local url="$1" label="$2" tries
  for tries in {1..40}; do
    if curl -fsS --max-time 1 "$url" >/dev/null 2>&1; then
      echo "[OK] $label ready: $url"
      return 0
    fi
    sleep 0.5
  done
  echo "[ERROR] $label did not become ready: $url" >&2
  return 1
}

if port_busy 8000; then
  if curl -fsS --max-time 2 http://127.0.0.1:8000/ >/dev/null 2>&1; then
    echo "[INFO] Existing HTTP server detected on port 8000; verify it is ExpoPulse."
  else
    echo "[ERROR] Port 8000 is busy and does not respond as expected. Stop that service first." >&2
    exit 1
  fi
else
  echo "[START] Django on port 8000"
  # --noreload keeps one predictable process to clean up.
  start_bg "$VENV_PY" manage.py runserver --noreload 127.0.0.1:8000
  wait_http http://127.0.0.1:8000/ "Django" || exit 1
fi

if [[ "$MODE" == equipment ]]; then
  if [[ -z "${EXPOPULSE_EQUIPMENT_API_TOKEN:-}" ]]; then
    echo "[ERROR] Set EXPOPULSE_EQUIPMENT_API_TOKEN in this terminal AND the Django server's environment." >&2
    echo "Example: export EXPOPULSE_EQUIPMENT_API_TOKEN='your-local-demo-token'" >&2
    exit 1
  fi
  echo "Dashboard: http://127.0.0.1:8000/"
  echo "[START] Equipment telemetry simulator (synthetic data)"
  exec_note="Press Ctrl+C to stop."
  echo "$exec_note"
  "$VENV_PY" manage.py simulate_equipment --interval 2 --loop
  exit 0
fi

case "$MODE" in
  crowd)
    VIDEO="footage/indoor_mall_cctv.mp4"
    LOCATION="Transport Hub"
    ;;
  restricted)
    VIDEO="footage/restricted_zone_normal.mp4"
    LOCATION="Zone A"
    ZONE="configs/restricted_zone.example.json"
    [[ -f "$ZONE" ]] || { echo "[ERROR] Missing zone config: $ZONE" >&2; exit 1; }
    ;;
  fall)
    VIDEO="footage/fall-01-rgb.mp4"
    LOCATION="Zone A"
    ;;
esac
[[ -f "$VIDEO" ]] || { echo "[ERROR] Missing video: $VIDEO" >&2; exit 1; }

# Single shared HLS URL; refuse to collide with an existing service.
if port_busy 8080; then
  echo "[ERROR] Port 8080 is already in use. Stop the other HLS demo/server before running this one." >&2
  exit 1
fi
STREAM_DIR="$ROOT/streams/demo_$MODE"
mkdir -p "$STREAM_DIR"
rm -f "$STREAM_DIR"/live.m3u8 "$STREAM_DIR"/*.ts

echo "[START] FFmpeg HLS stream for $MODE"
start_bg ffmpeg -nostdin -loglevel warning -re -stream_loop -1 -i "$VIDEO" \
  -an -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
  -f hls -hls_time 2 -hls_list_size 5 \
  -hls_flags delete_segments+omit_endlist "$STREAM_DIR/live.m3u8"

echo "[START] HLS HTTP server on port 8080"
start_bg "$VENV_PY" -m http.server 8080 --bind 127.0.0.1 --directory "$STREAM_DIR"
wait_http http://127.0.0.1:8080/live.m3u8 "HLS playlist" || exit 1

echo "Dashboard: http://127.0.0.1:8000/"
echo "Stream:    http://127.0.0.1:8080/live.m3u8"
echo "Module:    $MODE | Location: $LOCATION"
echo "Press Ctrl+C to stop all processes launched by this runner."
case "$MODE" in
  crowd)
    "$VENV_PY" manage.py detect_crowding \
      --video http://127.0.0.1:8080/live.m3u8 --location "$LOCATION" \
      --threshold 5 --frames 3 --sample-every 5
    ;;
  restricted)
    "$VENV_PY" manage.py detect_restricted_area \
      --video http://127.0.0.1:8080/live.m3u8 --location "$LOCATION" \
      --zone-config "$ZONE" --confirm-frames 5 --sample-every 1 --confidence 0.35
    ;;
  fall)
    "$VENV_PY" manage.py detect_falls \
      --video http://127.0.0.1:8080/live.m3u8 --location "$LOCATION" \
      --sample-every 3 --confirm-frames 5 --confidence 0.25 \
      --retry-delay 5 --max-retries 0
    ;;
esac
