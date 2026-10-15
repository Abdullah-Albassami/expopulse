#!/usr/bin/env bash
# ExpoPulse combined monitoring runner (macOS Bash 3.2+).
# Usage: ./run_simulation.sh {crowd|restricted|fall|all}
# 'all' runs CCTV detectors and the real Paris Open Data equipment status feed.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
MODE="${1:-}"
case "$MODE" in
  crowd|restricted|fall|all) ;;
  *) echo "Usage: ./run_simulation.sh {crowd|restricted|fall|all}" >&2; exit 2 ;;
esac

VENV_PY="$ROOT/venv/bin/python"
export PYTHONUNBUFFERED=1
[[ -x "$VENV_PY" ]] || { echo "[ERROR] Missing venv/bin/python." >&2; exit 1; }
[[ -f "$ROOT/manage.py" ]] || { echo "[ERROR] Missing manage.py." >&2; exit 1; }
for tool in ffmpeg curl lsof; do
  command -v "$tool" >/dev/null || { echo "[ERROR] Missing $tool." >&2; exit 1; }
done

OWNED_PIDS=()
CLEANED=0
cleanup() {
  if [[ "$CLEANED" == 1 ]]; then return; fi
  CLEANED=1
  trap - EXIT INT TERM
  echo
  echo "[STOP] Stopping processes started by this runner..."
  # Explicitly guard empty arrays for macOS Bash 3.2 with set -u.
  for pid in "${OWNED_PIDS[@]+"${OWNED_PIDS[@]}"}"; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in "${OWNED_PIDS[@]+"${OWNED_PIDS[@]}"}"; do
    wait "$pid" 2>/dev/null || true
  done
  echo "[OK] Runner cleanup complete."
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
  local url="$1" label="$2" n
  for ((n=0; n<60; n++)); do
    if curl -fsS --max-time 1 "$url" >/dev/null 2>&1; then
      echo "[OK] $label ready: $url"
      return 0
    fi
    sleep 0.5
  done
  echo "[ERROR] $label did not become ready: $url" >&2
  return 1
}
require_file() {
  [[ -f "$1" ]] || { echo "[ERROR] Missing $1" >&2; exit 1; }
}

# Reuse a running Django instance; never terminate processes we did not start.
if [[ "$MODE" == all && -z "${EXPOPULSE_EQUIPMENT_API_TOKEN:-}" ]]; then
  echo "[ERROR] Export EXPOPULSE_EQUIPMENT_API_TOKEN before running all." >&2
  exit 1
fi

if port_busy 8000; then
  if curl -fsS --max-time 2 http://127.0.0.1:8000/ >/dev/null 2>&1; then
    if [[ "$MODE" == all ]]; then
      echo "[ERROR] Port 8000 occupied. Stop the existing server; all mode must start Django with the matching equipment API token." >&2
      exit 1
    fi
    echo "[INFO] Reusing HTTP service on port 8000; confirm it is ExpoPulse."
  else
    echo "[ERROR] Port 8000 is occupied by an unresponsive HTTP service." >&2
    exit 1
  fi
else
  echo "[START] Django (port 8000)"
  start_bg "$VENV_PY" manage.py runserver --noreload 127.0.0.1:8000
  wait_http http://127.0.0.1:8000/ "Django"
fi

start_stream() {
  local name="$1" port="$2" video="$3" dir="$4" logdir="$5"
  require_file "$video"
  if port_busy "$port"; then
    echo "[ERROR] Port $port is occupied. Stop its existing HLS service first." >&2
    exit 1
  fi
  mkdir -p "$dir" "$logdir"
  rm -f "$dir"/live.m3u8 "$dir"/*.ts
  echo "[START] $name video stream on port $port"
  ffmpeg -nostdin -loglevel warning -re -stream_loop -1 -i "$video" \
    -an -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
    -f hls -hls_time 2 -hls_list_size 5 \
    -hls_flags delete_segments+omit_endlist "$dir/live.m3u8" \
    >"$logdir/$name.ffmpeg.log" 2>&1 &
  OWNED_PIDS+=("$!")
  "$VENV_PY" -m http.server "$port" --bind 127.0.0.1 --directory "$dir" \
    >"$logdir/$name.http.log" 2>&1 &
  OWNED_PIDS+=("$!")
  wait_http "http://127.0.0.1:$port/live.m3u8" "$name HLS"
}

run_detector() {
  local name="$1" port="$2"
  local url="http://127.0.0.1:$port/live.m3u8"
  case "$name" in
    crowd)
      exec "$VENV_PY" manage.py detect_crowding --video "$url" \
        --location "Transport Hub" --threshold 5 --frames 3 --sample-every 5 --demo-priority high ;;
    restricted)
      exec "$VENV_PY" manage.py detect_restricted_area --video "$url" \
        --location "Zone A" --zone-config configs/restricted_zone.example.json \
        --confirm-frames 5 --sample-every 1 --confidence 0.35 --demo-priority medium ;;
    fall)
      exec "$VENV_PY" manage.py detect_falls --video "$url" \
        --location "Zone A" --sample-every 3 --confirm-frames 5 \
        --confidence 0.25 --retry-delay 5 --max-retries 0 --demo-priority critical ;;
  esac
}

require_file configs/restricted_zone.example.json
LOG_DIR="$ROOT/streams/logs"
mkdir -p "$LOG_DIR"
echo "[DEMO] Incident priorities: restricted=MEDIUM, crowd=HIGH, fall=CRITICAL (simulation only)."
echo "Dashboard: http://127.0.0.1:8000/"

if [[ "$MODE" != all ]]; then
  case "$MODE" in
    crowd) VIDEO=footage/indoor_mall_cctv.mp4 ;;
    restricted) VIDEO=footage/restricted_zone_normal.mp4 ;;
    fall) VIDEO=footage/fall-01-rgb.mp4 ;;
  esac
  start_stream "$MODE" 8080 "$VIDEO" "$ROOT/streams/demo_$MODE" "$LOG_DIR"
  echo "[RUN] $MODE detector. Press Ctrl+C to stop."
  run_detector "$MODE" 8080
else
  # Dedicated ports allow all three live feeds to operate concurrently.
  # Preflight before creating streams, to avoid partially starting on port collisions.
  for port in 8081 8082 8083; do
    if port_busy "$port"; then
      echo "[ERROR] Port $port is already in use; cannot start all mode." >&2
      exit 1
    fi
  done
  require_file footage/indoor_mall_cctv.mp4
  require_file footage/restricted_zone_normal.mp4
  require_file footage/fall-01-rgb.mp4
  start_stream crowd 8081 footage/indoor_mall_cctv.mp4 "$ROOT/streams/all_crowd" "$LOG_DIR"
  start_stream restricted 8082 footage/restricted_zone_normal.mp4 "$ROOT/streams/all_restricted" "$LOG_DIR"
  start_stream fall 8083 footage/fall-01-rgb.mp4 "$ROOT/streams/all_fall" "$LOG_DIR"
  for spec in "crowd 8081" "restricted 8082" "fall 8083"; do
    read -r name port <<< "$spec"
    run_detector "$name" "$port" >"$LOG_DIR/$name.detector.log" 2>&1 &
    OWNED_PIDS+=("$!")
    echo "[RUN] $name detector PID $! | log: streams/logs/$name.detector.log"
  done
  echo "[START] Live Paris equipment-status polling (every 300 seconds)"
  "$VENV_PY" manage.py monitor_equipment_feed --live --polls 0 --poll-interval 300 >"$LOG_DIR/equipment.detector.log" 2>&1 &
  OWNED_PIDS+=("$!")
  echo "[RUN] equipment monitor PID $! | log: streams/logs/equipment.detector.log"
  echo "[OK] Three CCTV detectors plus live external equipment monitoring running."
  echo "Follow logs: tail -f streams/logs/{crowd,restricted,fall,equipment}.detector.log"
  echo "Press Ctrl+C to stop the processes started by this runner."
  # Bash 3.2 lacks wait -n. Check child liveness periodically instead.
  while true; do
    sleep 2
    for pid in "${OWNED_PIDS[@]+"${OWNED_PIDS[@]}"}"; do
      if ! kill -0 "$pid" 2>/dev/null; then
        echo "[ERROR] A simulation process (PID $pid) exited; see streams/logs/." >&2
        exit 1
      fi
    done
  done
fi
