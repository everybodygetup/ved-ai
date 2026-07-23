import sqlite3
from pathlib import Path

from monitoring.alta import AltaDocument


BASE_DIR = Path(__file__).resolve().parent.parent

DATABASE_PATH = (
    BASE_DIR
    / "data"
    / "monitor.db"
)

SOURCE_NAME = "alta_calendar_added"


def initialize_monitor_database() -> None:
    """Создаёт базу мониторинга и таблицу документов."""

    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with _connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS monitored_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                source_id TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                published TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(source, source_id)
            )
            """
        )


def count_documents(
    source: str = SOURCE_NAME,
) -> int:
    """Возвращает число сохранённых документов источника."""

    with _connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM monitored_documents
            WHERE source = ?
            """,
            (source,),
        ).fetchone()

    return int(row[0])


def save_new_documents(
    documents: list[AltaDocument],
    source: str = SOURCE_NAME,
) -> list[AltaDocument]:
    """
    Сохраняет документы.

    Возвращает только те, которых раньше не было в базе.
    """

    new_documents: list[AltaDocument] = []

    with _connect() as connection:
        for document in documents:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO monitored_documents (
                    source,
                    source_id,
                    title,
                    link,
                    published,
                    summary
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    document.source_id,
                    document.title,
                    document.link,
                    document.published,
                    document.summary,
                ),
            )

            if cursor.rowcount == 1:
                new_documents.append(document)

    return new_documents


def _connect() -> sqlite3.Connection:
    """Открывает соединение с SQLite."""

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    connection.row_factory = sqlite3.Row

    return connection