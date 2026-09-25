#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="${0:A:h}"
BACKEND_DIR="${SCRIPT_DIR:h}"
PROJECT_ROOT="${BACKEND_DIR:h}"
DOCKER_BIN="/usr/local/bin/docker"
PYTHON_BIN="${PROJECT_ROOT}/.venv/bin/python"
mode="${1:-snapshot}"

if [[ "$mode" != "snapshot" && "$mode" != "--check" ]]; then
  print -u2 -- "Usage: $0 [snapshot|--check]"
  exit 2
fi

if [[ ! -x "$DOCKER_BIN" ]]; then
  print -u2 -- "Docker CLI is unavailable at the configured path."
  exit 1
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  print -u2 -- "Project Python environment is unavailable."
  exit 1
fi

cd "$BACKEND_DIR"
container_id="$("$DOCKER_BIN" compose --project-name siderfold --file "${BACKEND_DIR}/compose.yaml" ps -q db)"
if [[ -z "$container_id" ]]; then
  print -u2 -- "The siderfold PostgreSQL service is not running; no snapshot was created."
  exit 1
fi

health_status="$("$DOCKER_BIN" inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}' "$container_id")"
if [[ "$health_status" != "healthy" ]]; then
  print -u2 -- "The siderfold PostgreSQL service is not healthy; no snapshot was created."
  exit 1
fi

published_address="$("$DOCKER_BIN" compose --project-name siderfold --file "${BACKEND_DIR}/compose.yaml" port db 5432)"
if [[ "$published_address" != 127.0.0.1:* ]]; then
  print -u2 -- "PostgreSQL is not bound to the expected local interface; no snapshot was created."
  exit 1
fi
published_port="${published_address##*:}"

# Read database credentials from the running primary container without printing them.
database_url="$("$DOCKER_BIN" inspect --format '{{json .Config.Env}}' "$container_id" | "$PYTHON_BIN" -c '
import json
import sys
from urllib.parse import quote

container_env = dict(item.split("=", 1) for item in json.load(sys.stdin))
database = container_env.get("POSTGRES_DB", "siderfold")
if database != "siderfold":
    raise SystemExit("Refusing to snapshot a database other than siderfold.")
user = container_env.get("POSTGRES_USER", "siderfold")
password = container_env.get("POSTGRES_PASSWORD", "siderfold")
port = sys.argv[1]
print("postgresql+psycopg://{}:{}@127.0.0.1:{}/{}".format(
    quote(user, safe=""), quote(password, safe=""), port, quote(database, safe="")
))
' "$published_port")"

DATABASE_URL="$database_url" "$PYTHON_BIN" -c '
from sqlalchemy import create_engine, text
from app.core.config import get_settings

engine = create_engine(get_settings().database_url)
try:
    with engine.connect() as connection:
        database = connection.scalar(text("select current_database()"))
finally:
    engine.dispose()
if database != "siderfold":
    raise SystemExit("Refusing to snapshot a database other than siderfold.")
print("Ready: primary database siderfold is reachable on its current Docker port.")
'

if [[ "$mode" == "--check" ]]; then
  exit 0
fi

DATABASE_URL="$database_url" "$PYTHON_BIN" -m app.analytics.cli
