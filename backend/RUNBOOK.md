# Local source operations

The source runner is intentionally a one-shot local command. It does not start
a daemon, enable a schedule, publish programs or send notifications outside the
machine.

## Before a run

Use the project's Python environment and migrate the local database:

```bash
cd backend
../.venv/bin/python -m alembic upgrade head
```

If the virtual environment has not been created yet, install the backend's
declared dependencies into an isolated environment first. The environment keeps
the project's Python packages separate from the macOS system Python.

Check the configured sources without contacting them:

```bash
../.venv/bin/siderfold-sources list
```

Run a local fixture through the complete protected path:

```bash
../.venv/bin/siderfold-sources run fixture-catalog
../.venv/bin/siderfold-sources runs --source-key fixture-catalog
```

`run` acquires a PostgreSQL advisory lock for the source. A competing command
does not wait or start a second parser; it records `skipped_locked` in the
execution journal instead.

## Review и публикация

Ниже — обычная последовательность для добавления проверенных данных в публичный
каталог. Она подходит для локальной операторской среды; автоматической
публикации или постоянного фонового запуска здесь нет.

1. Запусти приложение с токеном внутреннего доступа. Токен не нужно записывать
   в файл проекта: задай его в терминале, из которого запускается backend.

   ```bash
   cd /path/to/siderfold
   export INTERNAL_API_TOKEN='длинный-случайный-токен'
   export INTERNAL_OPERATOR_ID='имя-оператора'
   ./scripts/start-local.sh api
   ```

2. В отдельном терминале подготовь доступ к той же локальной БД. Docker выдаёт
   свободный порт, поэтому не следует предполагать, что PostgreSQL доступен на
   `5432`.

   ```bash
   cd /path/to/siderfold/backend
   DB_PORT="$(docker compose --project-name siderfold port db 5432 | awk -F: '{print $NF}' | tr -d '\r')"
   export DATABASE_URL="postgresql+psycopg://siderfold:siderfold@127.0.0.1:${DB_PORT}/siderfold"
   export INTERNAL_API_TOKEN='тот-же-токен'
   ```

3. Сначала запусти адаптер в `dry-run` и прочитай отчёт. Не запускай запись в
   БД, если формат источника неожиданно изменился, в отчёте есть ошибки или
   непонятные предупреждения.

   ```bash
   ../.venv/bin/python -m app.sources.cli dry-run potanin-competitions
   ```

4. Если отчёт приемлем, выполни управляемый запуск источника. Он сохраняет
   provenance, raw-метаданные и staging-кандидатов, но не создаёт опубликованные
   программы сам по себе.

   ```bash
   ../.venv/bin/python -m app.sources.cli run potanin-competitions
   ```

5. Посмотри созданный import-батч, очередь и детали конкретного кандидата.

   ```bash
   curl -sS -H "Authorization: Bearer $INTERNAL_API_TOKEN" \
     http://127.0.0.1:8000/api/internal/v1/ingestion-runs

   curl -sS -H "Authorization: Bearer $INTERNAL_API_TOKEN" \
     http://127.0.0.1:8000/api/internal/v1/review/cases

   curl -sS -H "Authorization: Bearer $INTERNAL_API_TOKEN" \
     http://127.0.0.1:8000/api/internal/v1/review/cases/<review_case_id>
   ```

   Warning означает, что поле неполное или требует оценки; оно не подменяется
   выдуманным значением. Ошибка блокирует принятие. Для решения нужно сверить
   нормализованные поля с первоисточником и доказательствами кандидата.

6. Прими решение через внутренний API. Каждый запрос на изменение требует новый
   `Idempotency-Key`; повтор того же запроса с тем же ключом безопасно вернёт
   прежний результат. `accept` публикует подтверждённую программу, `reject`
   оставляет доказательства в истории, `needs_clarification` возвращает кейс на
   уточнение. `merge` допустим только при явном подтверждённом совпадении и
   требует `deduplication_match_id` из деталей кейса.

   ```bash
   export REVIEW_CASE_ID='<review_case_id>'
   export IDEMPOTENCY_KEY="accept-$(uuidgen)"

   curl -sS -X POST \
     -H "Authorization: Bearer $INTERNAL_API_TOKEN" \
     -H "Content-Type: application/json" \
     -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
     -d '{"action":"accept","reason":"Данные сверены с официальной страницей источника."}' \
     "http://127.0.0.1:8000/api/internal/v1/review/cases/$REVIEW_CASE_ID/actions"
   ```

7. Убедись, что опубликованная программа появилась в public API и в каталоге,
   запущенном в API-режиме. Internal endpoints и технические данные review в
   public API не попадают.

   ```bash
   curl -sS http://127.0.0.1:8000/api/v1/programs
   ```

Пока модерация управляется API, а не отдельной веб-страницей. Не изменяй
канонические таблицы напрямую: это обойдёт ограничения, идемпотентность и audit
trail.

## Scheduling deliberately

`schedule-once` evaluates cron expressions in UTC, starts due active sources,
and exits:

```bash
../.venv/bin/siderfold-sources schedule-once
../.venv/bin/siderfold-sources schedule-once --at 2026-09-01T04:15:00+00:00
```

The checked-in sources are `manual`, so this command currently selects none.
Do not change a network source to a cron expression until its permitted access,
owner and acceptable frequency have been reviewed. After that decision, a host
scheduler such as `launchd` or cron may call the command at a bounded cadence;
the repository itself must not create that scheduler entry.

Example cron entry, added by the operator rather than the application:

```text
* * * * * /absolute/path/to/.venv/bin/siderfold-sources schedule-once >> /absolute/path/to/siderfold-scheduler.log 2>&1
```

Each source also has `min_run_interval_seconds` in `config/sources.toml`.
The scheduler records a rate-limited attempt instead of making a second request
too soon. Existing request, byte and transport-time limits remain in effect.

## Failures and recovery

The runner retries only temporary transport, HTTP 408/429/5xx and database
availability failures. It makes at most three attempts with bounded backoff.
Configuration, allowlist, parser, validation and other HTTP 4xx failures are
terminal and are not retried.

A successful empty poll is recorded as `empty_success`. Any report containing
errors is `failed`, even if it contains zero records. A failure from one source
does not prevent the same scheduler tick from trying the next due source.

The command writes a redacted JSON notification to stderr only for a failed
execution. It contains the source key, execution ID and error codes; it never
includes response bodies, cookies, tokens or exception text. There are no
webhooks or external notification integrations.

If a process is interrupted, PostgreSQL releases its advisory lock when that
database session closes. The next protected run marks the unfinished operation
and any matching `IngestionRun` as interrupted/failed before it starts fresh.
Do not clear advisory locks manually. Inspect the journal first:

```bash
../.venv/bin/siderfold-sources runs --limit 50
```

## Journal retention

Execution rows contain timing, outcome, retries, import counters, field-error
counts, freshness and the two review-queue sizes. They are operational metadata;
raw captures, staging records and provenance are not removed by journal cleanup.

Retention defaults to 90 days through `SCHEDULER_JOURNAL_RETENTION_DAYS`. Cleanup
is always explicit:

```bash
../.venv/bin/siderfold-sources prune-journal --retention-days 90
```

Run this only after checking the journal and only for local operational history
that is no longer needed. The command never runs automatically.
