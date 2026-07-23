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
    """Создаёт таблицы документов и подписчиков."""

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

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS monitor_subscribers (
                chat_id INTEGER PRIMARY KEY,
                user_id INTEGER,
                username TEXT NOT NULL DEFAULT '',
                full_name TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                subscribed_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def count_documents(
    source: str = SOURCE_NAME,
) -> int:
    """Возвращает количество сохранённых документов."""

    with _connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*)
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
    """Сохраняет документы и возвращает только новые."""

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


def subscribe_chat(
    chat_id: int,
    user_id: int | None,
    username: str,
    full_name: str,
) -> bool:
    """
    Активирует подписку.

    Возвращает True, если это новая или восстановленная подписка.
    """

    with _connect() as connection:
        previous = connection.execute(
            """
            SELECT is_active
            FROM monitor_subscribers
            WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()

        connection.execute(
            """
            INSERT INTO monitor_subscribers (
                chat_id,
                user_id,
                username,
                full_name,
                is_active
            )
            VALUES (?, ?, ?, ?, 1)

            ON CONFLICT(chat_id) DO UPDATE SET
                user_id = excluded.user_id,
                username = excluded.username,
                full_name = excluded.full_name,
                is_active = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                chat_id,
                user_id,
                username,
                full_name,
            ),
        )

    return (
        previous is None
        or int(previous["is_active"]) == 0
    )


def unsubscribe_chat(
    chat_id: int,
) -> bool:
    """Отключает подписку пользователя."""

    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE monitor_subscribers
            SET
                is_active = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE
                chat_id = ?
                AND is_active = 1
            """,
            (chat_id,),
        )

    return cursor.rowcount == 1


def deactivate_subscriber(
    chat_id: int,
) -> None:
    """Отключает недоступного подписчика."""

    with _connect() as connection:
        connection.execute(
            """
            UPDATE monitor_subscribers
            SET
                is_active = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE chat_id = ?
            """,
            (chat_id,),
        )


def get_active_subscriber_chat_ids() -> list[int]:
    """Возвращает chat_id активных подписчиков."""

    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT chat_id
            FROM monitor_subscribers
            WHERE is_active = 1
            ORDER BY subscribed_at
            """
        ).fetchall()

    return [
        int(row["chat_id"])
        for row in rows
    ]


def _connect() -> sqlite3.Connection:
    """Открывает соединение с SQLite."""

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    connection.row_factory = sqlite3.Row

    return connection