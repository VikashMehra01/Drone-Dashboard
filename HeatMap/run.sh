#!/usr/bin/env bash
# run.sh — start the whole SkyWatch stack (backend + frontend) with one command.
#
# No database process to start: SkyWatch uses a single local SQLite file
# (backend/skywatch.db), created and migrated automatically by the backend
# on startup — nothing to run for it here.
#
# This does NOT start MediaMTX/FFmpeg or any stream_processor.py drone feed
# — those are launched per-drone from the dashboard (Admin -> Add Drone), or
# manually as described in README.md / RUNBOOK.md.

set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"

# ── Locate the shared venv (backend + cv_pipeline) ──────────────────────────
# Checked in the same order as backend/app/routers/auth.py's _resolve_paths():
# an in-repo backend/venv first, then the actual shared venv one level above
# the project root, then whatever "python3" is on PATH as a last resort.
if [ -x "$BACKEND_DIR/venv/bin/python" ]; then
    VENV_PY="$BACKEND_DIR/venv/bin/python"
elif [ -x "$ROOT_DIR/../venv/bin/python" ]; then
    VENV_PY="$ROOT_DIR/../venv/bin/python"
else
    echo "No project venv found (checked backend/venv and ../venv)." >&2
    echo "Create one first — see README.md 'Create the Python Environment':" >&2
    echo "  python3.10 -m venv ../venv && source ../venv/bin/activate && pip install -r requirements.txt" >&2
    VENV_PY="python3"
    echo "Falling back to system '$VENV_PY' — this will likely fail on missing deps." >&2
fi

if ! "$VENV_PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    echo "Backend dependencies aren't installed in $VENV_PY." >&2
    echo "Run: $VENV_PY -m pip install -r \"$ROOT_DIR/requirements.txt\"" >&2
    exit 1
fi

# ── .env ──────────────────────────────────────────────────────────────────
if [ ! -f "$ROOT_DIR/.env" ] && [ -f "$ROOT_DIR/.env.example" ]; then
    cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
    echo "Created .env from .env.example (edit it if you need non-default secrets)."
fi

# ── Frontend deps ────────────────────────────────────────────────────────
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "Installing frontend dependencies (first run only)..."
    (cd "$FRONTEND_DIR" && npm install)
fi

# ── Launch backend + frontend ───────────────────────────────────────────────
# uvicorn's --reload watcher forks a separate server subprocess, and `npm run
# dev` forks vite as its own child — killing just the top-level PID leaves
# those running. kill_tree walks pgrep -P recursively (deepest first) so the
# whole subtree actually stops; this is more reliable across environments
# than relying on process-group signals (setsid/job-control based grouping
# behaves inconsistently under nohup/non-interactive shells).
PIDS=()

kill_tree() {
    local pid="$1" sig="$2" child
    for child in $(pgrep -P "$pid" 2>/dev/null); do
        kill_tree "$child" "$sig"
    done
    kill -"$sig" "$pid" 2>/dev/null
}

cleanup() {
    echo
    echo "Shutting down..."
    for pid in "${PIDS[@]}"; do
        kill_tree "$pid" TERM
    done
    sleep 1
    for pid in "${PIDS[@]}"; do
        kill_tree "$pid" KILL
    done
}
trap cleanup EXIT INT TERM

echo "Starting backend on http://$BACKEND_HOST:$BACKEND_PORT ..."
(
    cd "$BACKEND_DIR" || exit 1
    exec "$VENV_PY" -m uvicorn app.main:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT"
) &
BACKEND_PID=$!
PIDS+=("$BACKEND_PID")

# Wait for the backend to actually be up before starting the frontend.
for _ in $(seq 1 30); do
    if curl -sf "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

echo "Starting frontend (vite dev server) ..."
(
    cd "$FRONTEND_DIR" || exit 1
    exec npm run dev
) &
FRONTEND_PID=$!
PIDS+=("$FRONTEND_PID")

cat <<EOF

SkyWatch is starting up:
  Backend:   http://localhost:$BACKEND_PORT   (health: http://localhost:$BACKEND_PORT/health)
  Frontend:  http://localhost:5173

Press Ctrl+C to stop both.
EOF

wait
