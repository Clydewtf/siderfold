# Backend

Здесь живёт backend Siderfold. Frontend из `site/` пока работает со своими
seed-данными и к API не подключён.

Стек: Python 3.11+, FastAPI, Uvicorn, PostgreSQL 16, SQLAlchemy, Alembic и
Pydantic Settings.

## Схема B2–B3

Каноническая программа всегда имеет primary source. В `ProgramSource` хранится
ссылка на конкретную страницу источника и время её проверки. Темы и география
связаны с программой через отдельные таблицы, deadline и funding —
необязательные связи один-к-одному.

Статус публикации принимает одно из значений: `draft`, `published`, `archived`.
Для опубликованной или архивной программы нужен `published_at`.

Финансирование не сводится к одной сумме: `exact`, `minimum`, `maximum` и
`range` сохраняют исходную форму значения. `unknown` означает, что сумму нельзя
достоверно установить, а `not_stated` — что источник её не сообщает. Эти
состояния не считаются нулём.

Для загрузок есть отдельный контур происхождения: `IngestionRun` →
`RawCapture` → `StagedRecord` → `ReviewDecision`. `DataQualityIssue` хранит
предупреждения и ошибки staging-записи. У опубликованной программы есть ссылка
на решение review, поэтому от неё можно восстановить source, запуск, raw capture
и staging-запись.

`RawCapture` хранит только метаданные: SHA-256, исходный URL, время получения,
формат, адаптер, HTTP-метаданные и внешнюю ссылку на содержимое. Бинарные файлы
и большие ответы в PostgreSQL не сохраняются. Raw capture и решения review
неизменяемы.

Staging начинается в `received`, проходит extraction и состояния качества
`warning`/`error`, затем review; только из `review` возможен переход в
`published` или `rejected`. Недопустимые переходы отклоняет PostgreSQL. Повтор
того же входа для того же source возвращает
существующий `IngestionRun` по детерминированному fingerprint. Автоматической
публикации нет: для `Program` нужны завершённый запуск, опубликованная
staging-запись и решение `publish`.

## Запуск API

Команды выполняются из этой папки. Виртуальное окружение можно держать вне
репозитория:

```bash
python3 -m venv /private/tmp/siderfold-backend-venv
source /private/tmp/siderfold-backend-venv/bin/activate
python -m pip install -e '.[test]'
```

Поднять PostgreSQL:

```bash
docker compose --project-name siderfold up -d db
docker compose --project-name siderfold ps
docker compose --project-name siderfold port db 5432
```

Порт БД выбирается Docker автоматически, поэтому локальный `5432` не
занимается. Имена контейнера, сети и volume относятся только к проекту
`siderfold` и не пересекаются с другими Compose-проектами.

Подставить порт из предыдущей команды и запустить API:

```bash
DB_PORT="$(docker compose --project-name siderfold port db 5432 | awk -F: '{print $NF}')"
export DATABASE_URL="postgresql+psycopg://siderfold:siderfold@127.0.0.1:${DB_PORT}/siderfold"
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Проверить в другом окне терминала:

```bash
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
```

`/healthz` отвечает, даже если БД недоступна. `/readyz` отвечает `200`, когда
удаётся выполнить `SELECT 1`, и `503`, если подключиться к PostgreSQL нельзя.

Для быстрой проверки недоступной БД можно запустить отдельный процесс так:

```bash
DATABASE_URL="postgresql+psycopg://siderfold:siderfold@127.0.0.1:1/siderfold" \
  uvicorn app.main:app --host 127.0.0.1 --port 8001
curl -i http://127.0.0.1:8001/healthz
curl -i http://127.0.0.1:8001/readyz
```

Обычный набор без PostgreSQL-инвариантов:

```bash
python -m pytest
```

Для полной проверки миграции и SQL-ограничений используется отдельная чистая
БД. Временный Compose-проект `siderfold-test` существует только на время
тестов; основной проект остаётся `siderfold`.

```bash
POSTGRES_DB=siderfold_test \
  docker compose --project-name siderfold-test up -d db
TEST_DB_PORT="$(docker compose --project-name siderfold-test port db 5432 | awk -F: '{print $NF}')"
export TEST_DATABASE_URL="postgresql+psycopg://siderfold:siderfold@127.0.0.1:${TEST_DB_PORT}/siderfold_test"

python -m pytest
docker compose --project-name siderfold-test down --volumes --remove-orphans
```

Тесты откажутся запускать миграционный rollback, если имя БД в
`TEST_DATABASE_URL` не оканчивается на `_test`.

Проверка Compose-файла:

```bash
docker compose --project-name siderfold config
```

Если основную локальную БД нужно создать заново с нуля:

```bash
docker compose --project-name siderfold down --volumes --remove-orphans
```

Эта команда удаляет только контейнер, volume и сеть проекта `siderfold`.
