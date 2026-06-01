#!/usr/bin/env bash
#
# Launch Microsoft Edge with CDP remote debugging enabled, on a dedicated
# user-data-dir seeded from the real Edge profile (so it carries the Improving
# tenant identity for SSO). Idempotent: if a debugging Edge is already up on the
# port it reuses it instead of launching a second one.
#
# Why a dedicated dir: Edge/Chromium 136+ refuse to enable --remote-debugging-port
# on the *default* profile directory. A separate user-data-dir is mandatory, and
# it lets this debug Edge coexist with any normal Edge/Chrome the user has open.
#
# Usage: launch_edge_cdp.sh [port]
# Output: prints "CDP_ENDPOINT=http://localhost:<port>" on success (exit 0).

set -euo pipefail

PORT="${1:-9333}"
DEBUG_DIR="$HOME/.edge-cdp-debug"
EDGE_BIN="/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"
SRC_DIR="$HOME/Library/Application Support/Microsoft Edge"
HOME_URL="https://wd5.myworkday.com/improving/d/home.htmld"

endpoint_up() {
  curl -sf "http://localhost:${PORT}/json/version" >/dev/null 2>&1
}

# 1. Reuse an already-running debug Edge on this port.
if endpoint_up; then
  echo "CDP_ENDPOINT=http://localhost:${PORT}"
  echo "STATUS=reused-existing"
  exit 0
fi

if [[ ! -x "$EDGE_BIN" ]]; then
  echo "ERROR: Microsoft Edge not found at: $EDGE_BIN" >&2
  exit 1
fi

# 2. Seed the dedicated debug profile from the real Edge profile on first use,
#    so it inherits the Improving tenant / IdP cookies. Skip if it already exists
#    (don't clobber an established, already-logged-in debug profile).
if [[ ! -d "$DEBUG_DIR" ]]; then
  if [[ -d "$SRC_DIR/Default" ]]; then
    echo "Seeding debug profile from real Edge profile (one-time)..." >&2
    mkdir -p "$DEBUG_DIR"
    cp "$SRC_DIR/Local State" "$DEBUG_DIR/Local State" 2>/dev/null || true
    rsync -a \
      --exclude 'Cache' --exclude 'Code Cache' --exclude 'GPUCache' \
      --exclude 'Service Worker/CacheStorage' --exclude 'DawnGraphiteCache' \
      --exclude 'DawnWebGPUCache' --exclude 'component_crx_cache' \
      "$SRC_DIR/Default/" "$DEBUG_DIR/Default/"
  else
    echo "No existing Edge profile to seed from; starting fresh." >&2
    mkdir -p "$DEBUG_DIR"
  fi
fi

# 3. Launch Edge detached with remote debugging. nohup + & so it outlives this
#    script; output goes to a log for debugging.
echo "Launching Edge with CDP on port ${PORT}..." >&2
nohup "$EDGE_BIN" \
  --remote-debugging-port="${PORT}" \
  --user-data-dir="$DEBUG_DIR" \
  --no-first-run --no-default-browser-check --no-service-autorun \
  --disable-features=Translate \
  "$HOME_URL" \
  >/tmp/edge-cdp-${PORT}.log 2>&1 &

# 4. Wait for the CDP endpoint to come up (up to ~20s).
for _ in $(seq 1 40); do
  if endpoint_up; then
    echo "CDP_ENDPOINT=http://localhost:${PORT}"
    echo "STATUS=launched"
    exit 0
  fi
  sleep 0.5
done

echo "ERROR: CDP endpoint did not come up on port ${PORT}. See /tmp/edge-cdp-${PORT}.log" >&2
exit 1
