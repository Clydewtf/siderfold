#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
SITE_DIR="$PROJECT_ROOT/site"
VENV_DIR="${SIDERFOLD_BACKEND_VENV:-}"
PYTHON_COMMAND="${SIDERFOLD_PYTHON:-}"
COMPOSE_PROJECT="${SIDERFOLD_COMPOSE_PROJECT:-siderfold}"
BACKEND_HOST="${SIDERFOLD_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${SIDERFOLD_BACKEND_PORT:-8000}"
FRONTEND_PORT="${SIDERFOLD_FRONTEND_PORT:-4191}"
POSTGRES_DB_VALUE="${POSTGRES_DB:-siderfold}"
POSTGRES_USER_VALUE="${POSTGRES_USER:-siderfold}"
POSTGRES_PASSWORD_VALUE="${POSTGRES_PASSWORD:-siderfold}"

BACKEND_PID=""
FRONTEND_PID=""
MODE="${1:-}"

fail() {
  printf 'Ошибка: %s\n' "$1" >&2
  exit 1
}

select_python() {
  local candidate
  local candidates=()

  if [[ -n "$PYTHON_COMMAND" ]]; then
    candidates=("$PYTHON_COMMAND")
  else
    # Prefer a stable interpreter when several supported versions are installed.
    candidates=(python3.12 python3.11 python3)
  fi

  for candidate in "${candidates[@]}"; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
      >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done

  return 1
}

is_valid_virtualenv() {
  local candidate_dir="$1"
  local candidate_python="$candidate_dir/bin/python"

  [[ -f "$candidate_dir/pyvenv.cfg" && -x "$candidate_python" ]] || return 1
  "$candidate_python" -c \
    'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix and sys.version_info >= (3, 11) else 1)' \
    >/dev/null 2>&1
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM

  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi

  if [[ -n "$FRONTEND_PID" ]]; then
    wait "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]]; then
    wait "$BACKEND_PID" 2>/dev/null || true
  fi

  exit "$exit_code"
}

trap cleanup EXIT INT TERM

command -v npm >/dev/null 2>&1 || fail "не найден npm."
command -v curl >/dev/null 2>&1 || fail "не найден curl."

if [[ "$MODE" == "--help" || "$MODE" == "-h" ]]; then
  printf 'Использование: %s [api|seed]\n' "$0"
  printf 'Без аргумента режим выбирается интерактивно.\n'
  exit 0
fi

if [[ -z "$MODE" ]]; then
  if [[ -t 0 ]]; then
    printf 'Выбери режим запуска:\n'
    printf '  1) API: backend, PostgreSQL и frontend\n'
    printf '  2) Seed: только frontend с демо-данными\n'
    printf 'Режим [1]: '
    if ! read -r mode_choice; then
      mode_choice="1"
    fi
    case "${mode_choice:-1}" in
      1) MODE="api" ;;
      2) MODE="seed" ;;
      *) fail "выбери 1 или 2." ;;
    esac
  else
    MODE="api"
  fi
fi

case "$MODE" in
  api|seed) ;;
  *) fail "неизвестный режим '$MODE'. Используй api или seed." ;;
esac

if [[ "$MODE" == "api" ]]; then
  command -v docker >/dev/null 2>&1 || fail "не найден Docker CLI. Запусти Docker Desktop."
  PYTHON_COMMAND="$(select_python)" \
    || fail "нужен Python 3.11 или новее. Можно явно задать SIDERFOLD_PYTHON."
  PYTHON_SERIES="$("$PYTHON_COMMAND" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  if [[ -z "$VENV_DIR" ]]; then
    VENV_DIR="/private/tmp/siderfold-backend-venv-py${PYTHON_SERIES}"
  fi
fi

if command -v lsof >/dev/null 2>&1; then
  if [[ "$MODE" == "api" ]] && lsof -nP -iTCP:"$BACKEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "порт backend $BACKEND_PORT уже занят. Заверши процесс вручную или задай SIDERFOLD_BACKEND_PORT."
  fi
  if lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    fail "порт frontend $FRONTEND_PORT уже занят. Заверши процесс вручную или задай SIDERFOLD_FRONTEND_PORT."
  fi
fi

if [[ "$MODE" == "api" ]]; then
  cd "$BACKEND_DIR"

  PYTHON_BIN="$VENV_DIR/bin/python"
  if [[ -e "$VENV_DIR" ]] && ! is_valid_virtualenv "$VENV_DIR"; then
    fail "каталог $VENV_DIR не является корректным virtualenv. Задай другой SIDERFOLD_BACKEND_VENV или удали только этот временный каталог и запусти команду снова."
  fi
  if ! is_valid_virtualenv "$VENV_DIR"; then
    printf 'Создаю виртуальное окружение: %s\n' "$VENV_DIR"
    "$PYTHON_COMMAND" -m venv "$VENV_DIR"
  fi

  PYTHON_BIN="$VENV_DIR/bin/python"
  is_valid_virtualenv "$VENV_DIR" \
    || fail "не удалось создать корректное виртуальное окружение."

  if ! "$PYTHON_BIN" -c 'import alembic, fastapi, sqlalchemy, uvicorn' >/dev/null 2>&1; then
    printf 'Устанавливаю зависимости backend...\n'
    "$PYTHON_BIN" -m pip install -e "${BACKEND_DIR}[test]"
  fi

  docker compose --project-name "$COMPOSE_PROJECT" version >/dev/null 2>&1 \
    || fail "Docker Compose недоступен. Проверь Docker Desktop."

  export POSTGRES_DB="$POSTGRES_DB_VALUE"
  export POSTGRES_USER="$POSTGRES_USER_VALUE"
  export POSTGRES_PASSWORD="$POSTGRES_PASSWORD_VALUE"

  docker compose --project-name "$COMPOSE_PROJECT" up -d db

  DB_PORT="$(docker compose --project-name "$COMPOSE_PROJECT" port db 5432 | awk -F: '{print $NF}' | tr -d '\r')"
  [[ "$DB_PORT" =~ ^[0-9]+$ ]] || fail "не удалось определить локальный порт PostgreSQL."

  printf 'Жду готовности PostgreSQL на порту %s...\n' "$DB_PORT"
  db_ready="false"
  for ((attempt = 1; attempt <= 30; attempt++)); do
    if docker compose --project-name "$COMPOSE_PROJECT" exec -T db \
      pg_isready -U "$POSTGRES_USER_VALUE" -d "$POSTGRES_DB_VALUE" >/dev/null 2>&1; then
      db_ready="true"
      break
    fi
    sleep 1
  done
  [[ "$db_ready" == "true" ]] || fail "PostgreSQL не успел перейти в готовое состояние."

  export DATABASE_URL="postgresql+psycopg://${POSTGRES_USER_VALUE}:${POSTGRES_PASSWORD_VALUE}@127.0.0.1:${DB_PORT}/${POSTGRES_DB_VALUE}"
  printf 'Применяю миграции...\n'
  "$PYTHON_BIN" -m alembic upgrade head

  printf 'Запускаю backend на http://%s:%s...\n' "$BACKEND_HOST" "$BACKEND_PORT"
  "$PYTHON_BIN" -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" &
  BACKEND_PID=$!

  backend_ready="false"
  for ((attempt = 1; attempt <= 30; attempt++)); do
    if curl --silent --show-error --fail --max-time 1 \
      "http://${BACKEND_HOST}:${BACKEND_PORT}/healthz" >/dev/null 2>&1; then
      backend_ready="true"
      break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      fail "backend завершился во время запуска."
    fi
    sleep 1
  done
  [[ "$backend_ready" == "true" ]] || fail "backend не ответил на health check."
fi

printf 'Запускаю frontend на http://127.0.0.1:%s...\n' "$FRONTEND_PORT"
(
  cd "$SITE_DIR"
  export VITE_DATA_MODE="$MODE"
  if [[ "$MODE" == "api" ]]; then
    export VITE_BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
  fi
  exec npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT"
) &
FRONTEND_PID=$!

frontend_ready="false"
for ((attempt = 1; attempt <= 30; attempt++)); do
  if curl --silent --show-error --fail --max-time 1 \
    "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
    frontend_ready="true"
    break
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    fail "frontend завершился во время запуска."
  fi
  sleep 1
done
[[ "$frontend_ready" == "true" ]] || fail "frontend не ответил на health check."

FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"
if [[ "$MODE" == "api" ]]; then
  printf '\nSiderfold запущен в API-режиме.\n'
else
  printf '\nSiderfold запущен в режиме seed-данных.\n'
fi
printf 'Frontend: %s\n' "$FRONTEND_URL"
if [[ "$MODE" == "api" ]]; then
  printf 'Backend environment: %s\n' "$PYTHON_BIN"
  printf 'Backend health: http://%s:%s/healthz\n' "$BACKEND_HOST" "$BACKEND_PORT"
  printf 'Операторская панель: %s/operator.html\n' "$FRONTEND_URL"
  if [[ -z "${INTERNAL_API_TOKEN:-}" ]]; then
    printf 'Для операторской панели сначала задай INTERNAL_API_TOKEN и перезапусти API-режим.\n'
  fi
  printf 'Для остановки backend и frontend нажми Ctrl+C. PostgreSQL останется запущенным.\n'
else
  printf 'Backend и PostgreSQL в этом режиме не запускаются.\n'
  printf 'Для остановки frontend нажми Ctrl+C.\n'
fi

if [[ "${SIDERFOLD_NO_OPEN:-0}" != "1" ]] && command -v open >/dev/null 2>&1; then
  open -u "$FRONTEND_URL" >/dev/null 2>&1 || printf 'Браузер не удалось открыть автоматически; используй URL выше.\n'
fi

while true; do
  if [[ "$MODE" == "api" ]] && ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    fail "backend завершился."
  fi
  if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
    fail "frontend завершился."
  fi
  sleep 1
done
