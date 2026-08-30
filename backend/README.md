# Backend

Здесь живёт backend Siderfold. Frontend из `site/` пока работает со своими
seed-данными и к API не подключён.

Стек: Python 3.11+, FastAPI, Uvicorn, PostgreSQL 16, SQLAlchemy, Alembic и
Pydantic Settings.

## Каноническая схема и provenance

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

## Локальный импорт

Bridge принимает локальный пакет `siderfold.import/v1` в JSON или CSV и
записывает его в уже существующий контур `RawCapture` → `StagedRecord`.
Для локального импорта используются существующие таблицы и ограничения.

В JSON пакет состоит из метаданных источника, capture, адаптера и массива
записей:

```json
{
  "contract_version": "siderfold.import/v1",
  "source": {"name": "Название", "canonical_url": "https://source.example"},
  "capture": {
    "source_url": "https://source.example/export",
    "received_at": "2026-08-30T12:00:00+00:00",
    "external_content_uri": "file:///absolute/path/package.json",
    "content_format": "application/json"
  },
  "adapter": {"name": "local-export", "version": "1.0.0"},
  "records": [
    {
      "record_key": "source:program:example",
      "title": "Название программы",
      "record_url": "https://source.example/program/example",
      "deadline_on": "2026-12-31",
      "funding": {
        "value_kind": "maximum",
        "currency_code": "RUB",
        "max_amount": "1000000"
      },
      "payload": {},
      "warnings": []
    }
  ]
}
```

`funding` необязателен. Если он указан, его значения обязаны соответствовать
`value_kind`: `exact`, `minimum`, `maximum`, `range`, `unknown` или
`not_stated`. Тем самым отсутствующая или неопределённая сумма не превращается
в ноль.

CSV содержит одну запись на строку. Метаданные пакета повторяются в каждой
строке и должны быть одинаковы. Порядок колонок не важен, но набор фиксирован:

```text
contract_version,source_name,source_canonical_url,capture_source_url,received_at,
external_content_uri,content_format,adapter_name,adapter_version,record_key,title,
record_url,deadline_on,funding_value_kind,currency_code,exact_amount,min_amount,
max_amount,payload_json,warnings_json
```

Поля `payload_json` и `warnings_json` содержат соответственно JSON-объект и
JSON-массив строк. Неверный пакет целиком возвращает `package_errors` и не
пишется в БД. Неверная отдельная строка создаёт staging-запись в состоянии
`error` с `DataQualityIssue`; корректные строки того же пакета доходят до
`review`.

Идемпотентность определяется fingerprint нормализованного пакета вместе с
source и версией адаптера. Идентичная повторная доставка возвращает прежний
`IngestionRun` и статусы `skipped`, не создавая второй raw capture или staging
записи. Изменённая запись с тем же `record_key` создаёт следующую staging-версию
и получает статус `updated`; предыдущее происхождение сохраняется.

Bridge не создаёт `Program` и `ReviewDecision`. Даже полностью корректный
импорт остаётся набором кандидатов до отдельного review.

Команда печатает JSON-отчёт версии `siderfold.import-report/v1`. В нём есть
`dry_run`, идентификаторы source/run/raw capture, счётчики `new_count`,
`updated_count`, `skipped_count`, `error_count`, массив `rows` и
`package_errors`. У строки указаны номер, `record_key`, статус, идентификатор
staging-записи, при обновлении предыдущая staging-запись и ошибки валидации.

После настройки `DATABASE_URL` и `alembic upgrade head` импорт можно выполнить
так:

```bash
python -m app.import_bridge.cli tests/fixtures/imports/potanin_import_v1.json --format json --dry-run
python -m app.import_bridge.cli tests/fixtures/imports/potanin_import_v1.csv --format csv --dry-run
```

Для локального JSON-вывода Потанина предусмотрен узкий адаптер только для
dry-run. Он читает файл на месте, не копирует его, не сохраняет крупное
содержимое в PostgreSQL и исключает поля контактов и полного текста из staging
payload:

```bash
python -m app.import_bridge.cli /path/to/competitions.json --format potanin-json --dry-run
```

Для контрактов JSON и CSV без `--dry-run` транзакция фиксируется; использовать
этот режим следует только после review отчёта.

## Внутренний read API

Read API имеет версию `/api/v1` и доступен только для чтения:

| Метод и путь | Назначение |
| --- | --- |
| `GET /api/v1/programs` | Список опубликованных программ |
| `GET /api/v1/programs/{program_id}` | Карточка опубликованной программы |
| `GET /api/v1/sources` | Источники, связанные с опубликованными программами |
| `GET /api/v1/filters` | Доступные источники, темы, география, виды финансирования и границы сроков |

Список программ принимает `page` (с 1), `page_size` (1–100, по умолчанию 20),
`sort` (`published_at`, `deadline`, `title`), `order` (`asc`, `desc`), `q`,
повторяемые `source_id`, `theme`, `geography`, `funding_kind`, а также
`deadline_from` и `deadline_to`. Значения внутри одного фильтра объединяются
через OR, разные фильтры — через AND. Сортировка всегда дополнительно
стабилизируется по `id`; пустая страница возвращает `200` с пустым `items`.
Список источников использует такую же пагинацию и поддерживает сортировку по
`name` или `program_count` и поиск по имени.

Все четыре endpoint-а работают только с `Program.publication_status = published`.
`draft` и `archived` не попадают в списки, источники или фильтры; запрос карточки
для такой программы возвращает тот же `404 program_not_found`, что и неизвестный
ID. Ответы формируются отдельными Pydantic-схемами, а не ORM-моделями.

Публичные ответы содержат только канонические поля программы, источника,
deadline, funding, тем и географии. В них намеренно отсутствуют `RawCapture`,
`StagedRecord`, `DataQualityIssue`, тексты предупреждений, `ReviewDecision`,
`candidate_payload`, fingerprint, данные адаптера и внутренние provenance ID.

Успешный список имеет форму `items`, `page`, `page_size`, `total`. Ошибки имеют
форму `{ "error": { "code", "message", "details" } }`: `422 invalid_request`,
`404 program_not_found`, `503 database_unavailable` и `500 internal_error`. Полная схема доступна в
генерируемом OpenAPI (`/docs` и `/openapi.json`).

## Реестр источников и адаптеры

Реестр хранится в `config/sources.toml` и содержит только операционные данные:
канонический URL, разрешённые префиксы и точные URL, способ доступа, лимиты,
расписание, статус, ответственного и версию адаптера. Значения секретов в репозитории не
хранятся; при необходимости конфигурация может ссылаться на имена переменных
окружения. Другой файл реестра можно передать через `SOURCE_REGISTRY_PATH`.

Все адаптеры используют один порядок работы: `discover` находит ресурсы,
`fetch` получает содержимое, `extract` выделяет записи, `validate` проверяет их,
`report` формирует итоговую статистику. Перед fetch проверяются схема, host и
path-prefix URL. Также применяются лимиты запросов, размера ответа, общего
объёма и количества записей. `timeout_seconds` уже входит в конфигурационный
контракт и будет применяться сетевым адаптером; локальный fixture-адаптер сети
не использует.

В репозитории есть локальный fixture-адаптер. Он не обращается в сеть и нужен для
проверки самого контура:

```bash
python -m app.sources.cli list
python -m app.sources.cli dry-run fixture-catalog
```

`dry-run` выполняет discovery, fetch, extraction и validation, но не создаёт
записи в PostgreSQL. Обычный запуск после настройки `DATABASE_URL` сохраняет
статистику в `IngestionRun`, raw-метаданные и staging-кандидатов, но не создаёт
`Program` и не публикует данные автоматически:

```bash
alembic upgrade head
python -m app.sources.cli run fixture-catalog
```

Отчёт имеет версию `siderfold.adapter-report/v1` и показывает статус, счётчики
discovery/fetch/extract/validation, ошибки, предупреждения и результат передачи
в существующий import bridge. Источники со статусом `paused` или `disabled` не
запускаются. Планировщик и сетевой HTTP-сбор пока не входят в этот контур.

### Фонд Потанина

Первый сетевой адаптер зарегистрирован как `potanin-competitions`. Discovery
читает только официальный sitemap
`https://fondpotanin.ru/sitemap-iblock-competitions.xml`, а затем только
карточки из `https://fondpotanin.ru/competitions/`. Ссылки на портал подачи,
документы, итоги и дополнительные условия сохраняются в staging как ссылки,
но адаптер их не открывает и не обходит.

Один запуск сохраняет отдельные raw capture для sitemap и для каждой карточки:
так у каждого staging-кандидата остаётся прямая связь с конкретным HTML. В
PostgreSQL записываются только метаданные и URI внешнего raw-файла; путь для
сетевых ответов задаётся `RAW_CAPTURE_DIR` (по умолчанию `/tmp/siderfold/raw`).
В dry-run внешние файлы не создаются.

В отчёте `quality` все доли содержат числитель и знаменатель:

- `completeness` — валидные кандидаты / URL карточек, принятые из sitemap;
- `validity` — валидные кандидаты / извлечённые записи;
- `duplicate_rate` — извлечённые записи с дубликатом / извлечённые записи;
- `freshness` — карточки с валидным `lastmod` / URL карточек, а также самый
  новый `lastmod` и время capture.

Эти метрики описывают только зафиксированный sitemap и ответ страниц в одном
запуске: они не подтверждают полноту сайта или актуальность условий конкурса.
Неполные, противоречивые и неожиданные данные остаются в staging с
`DataQualityIssue`; создание `Program` не происходит автоматически.

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
