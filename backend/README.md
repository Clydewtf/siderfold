# Backend

Здесь пока только базовый API-каркас для следующего этапа. Frontend из
`site/` к нему не подключён.

Стек: Python 3.11+, FastAPI, Uvicorn, PostgreSQL 16, SQLAlchemy, Alembic и
Pydantic Settings.

## Запуск

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

Тесты и проверка Compose-файла:

```bash
python -m pytest
docker compose --project-name siderfold config
```

Если БД нужно создать заново с нуля:

```bash
docker compose --project-name siderfold down --volumes --remove-orphans
```

Эта команда удаляет только контейнер, volume и сеть проекта `siderfold`.
Модели источников и программ появятся на следующем этапе вместе с первой
полноценной схемой.
