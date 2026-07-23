import asyncio
import html
import logging
import re
from dataclasses import dataclass
from typing import Final

import httpx
from bs4 import BeautifulSoup, Tag

from monitoring.alta import AltaDocument


logger = logging.getLogger(__name__)


REQUEST_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,"
        "application/xhtml+xml,"
        "application/xml;q=0.9,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
    "Connection": "close",
}


KNOWN_STATUSES: Final[dict[str, str]] = {
    "документ действует": "Документ действует",
    "документ не действует": "Документ не действует",
    "документ частично не действует": (
        "Документ частично не действует"
    ),
    "статус не определен": "Статус не определён",
    "статус не определён": "Статус не определён",
}


# Тексты интерфейса Alta, которые нельзя принимать
# за статус или дату вступления в силу.
SERVICE_LABELS: Final[set[str]] = {
    "история статусов",
    "статус документа",
    "информация о статусе документа",
    "подробная информация о датах и статусах документа",
    "таможенный календарь",
    "добавлен в базу",
    "скачать документ",
    "печатная версия",
    "предыдущий документ",
    "следующий документ",
}


DATE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b\d{2}\.\d{2}\.\d{4}\b"
)


@dataclass(slots=True, frozen=True)
class AltaDocumentDetails:
    """Сведения, извлечённые со страницы документа Alta."""

    source_id: str
    title: str
    link: str
    published: str
    calendar_link: str

    calendar_summary: str
    status: str
    effective_date: str
    text_excerpt: str

    extraction_error: str = ""


async def fetch_documents_details(
    documents: list[AltaDocument],
    max_documents: int = 10,
) -> list[AltaDocumentDetails]:
    """Загружает подробности нескольких документов."""

    selected_documents = documents[:max_documents]

    if not selected_documents:
        return []

    semaphore = asyncio.Semaphore(3)

    async def load_one(
        document: AltaDocument,
    ) -> AltaDocumentDetails:
        try:
            async with semaphore:
                return await fetch_document_details(
                    document
                )

        except Exception as error:
            logger.exception(
                "Не удалось прочитать документ Alta: %s",
                document.link,
            )

            return AltaDocumentDetails(
                source_id=document.source_id,
                title=document.title,
                link=document.link,
                published=document.published,
                calendar_link=document.calendar_link,
                calendar_summary=document.summary,
                status="Не удалось определить",
                effective_date="Не удалось подтвердить",
                text_excerpt=document.summary,
                extraction_error=(
                    f"{type(error).__name__}: {error}"
                ),
            )

    tasks = [
        load_one(document)
        for document in selected_documents
    ]

    return list(
        await asyncio.gather(*tasks)
    )


async def fetch_document_details(
    document: AltaDocument,
    max_text_chars: int = 5000,
) -> AltaDocumentDetails:
    """Открывает и анализирует страницу одного документа."""

    page_content = await _download_page(
        document.link
    )

    soup = BeautifulSoup(
        page_content,
        "html.parser",
    )

    title = _extract_title(
        soup=soup,
        fallback=document.title,
    )

    full_text = _extract_main_text(
        soup
    )

    status = _extract_status(
        full_text
    )

    effective_date = _extract_effective_date(
        full_text=full_text,
        calendar_published=document.published,
    )

    excerpt = _build_text_excerpt(
        full_text=full_text,
        title=title,
        max_chars=max_text_chars,
    )

    logger.info(
        "Документ Alta прочитан: "
        "url=%s, символов=%s, статус=%r, вступление=%r",
        document.link,
        len(full_text),
        status,
        effective_date,
    )

    return AltaDocumentDetails(
        source_id=document.source_id,
        title=title,
        link=document.link,
        published=document.published,
        calendar_link=document.calendar_link,
        calendar_summary=document.summary,
        status=status,
        effective_date=effective_date,
        text_excerpt=excerpt,
    )


async def _download_page(
    page_url: str,
) -> bytes:
    """Скачивает страницу документа с повторами."""

    timeout = httpx.Timeout(
        connect=15.0,
        read=40.0,
        write=20.0,
        pool=15.0,
    )

    last_error: Exception | None = None

    for trust_env in (True, False):
        mode_name = (
            "с системными настройками"
            if trust_env
            else "без системного прокси"
        )

        for attempt in range(1, 4):
            try:
                logger.info(
                    "Загружаю документ Alta: "
                    "попытка=%s, режим=%s, url=%s",
                    attempt,
                    mode_name,
                    page_url,
                )

                async with httpx.AsyncClient(
                    timeout=timeout,
                    follow_redirects=True,
                    headers=REQUEST_HEADERS,
                    trust_env=trust_env,
                    http2=False,
                ) as client:
                    response = await client.get(
                        page_url
                    )

                    response.raise_for_status()

                if not response.content:
                    raise RuntimeError(
                        "Страница документа пустая."
                    )

                logger.info(
                    "Страница документа Alta получена: "
                    "status=%s, bytes=%s",
                    response.status_code,
                    len(response.content),
                )

                return response.content

            except (
                httpx.RequestError,
                httpx.HTTPStatusError,
                RuntimeError,
            ) as error:
                last_error = error

                logger.warning(
                    "Ошибка загрузки документа: "
                    "попытка=%s, режим=%s, "
                    "ошибка=%s: %s",
                    attempt,
                    mode_name,
                    type(error).__name__,
                    error,
                )

                if attempt < 3:
                    await asyncio.sleep(
                        attempt * 2
                    )

    raise RuntimeError(
        "Не удалось получить страницу документа: "
        f"{type(last_error).__name__ if last_error else 'UnknownError'}: "
        f"{last_error or 'причина неизвестна'}"
    )


def _extract_title(
    soup: BeautifulSoup,
    fallback: str,
) -> str:
    """Извлекает заголовок документа."""

    selectors = (
        "h1",
        "main h2",
        "article h2",
        ".page-title",
        ".document-title",
    )

    for selector in selectors:
        heading = soup.select_one(
            selector
        )

        if not isinstance(heading, Tag):
            continue

        title = _clean_text(
            heading.get_text(
                " ",
                strip=True,
            )
        )

        if title:
            return title

    return fallback


def _extract_main_text(
    soup: BeautifulSoup,
) -> str:
    """Извлекает видимый текст страницы документа."""

    for unwanted in soup.find_all(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "form",
            "iframe",
            "template",
        ]
    ):
        unwanted.decompose()

    candidates: list[Tag] = []

    selectors = (
        "main",
        "article",
        "[role='main']",
        ".page-content",
        ".document-content",
        ".tamdoc-content",
        ".content",
        ".b-text",
    )

    for selector in selectors:
        element = soup.select_one(
            selector
        )

        if isinstance(element, Tag):
            candidates.append(
                element
            )

    if isinstance(soup.body, Tag):
        candidates.append(
            soup.body
        )

    if not candidates:
        return ""

    main_container = max(
        candidates,
        key=lambda element: len(
            element.get_text(
                " ",
                strip=True,
            )
        ),
    )

    raw_text = main_container.get_text(
        "\n",
        strip=True,
    )

    lines: list[str] = []
    previous_line = ""

    for raw_line in raw_text.splitlines():
        line = _clean_text(
            raw_line
        )

        if not line:
            continue

        if line == previous_line:
            continue

        previous_line = line
        lines.append(
            line
        )

    return "\n".join(lines)


def _extract_status(
    full_text: str,
) -> str:
    """Ищет только известные явные статусы Alta."""

    lines = _prepare_lines(
        full_text
    )

    for index, line in enumerate(lines):
        normalized = _normalize_line(
            line
        )

        if normalized in KNOWN_STATUSES:
            return KNOWN_STATUSES[
                normalized
            ]

        inline_match = re.fullmatch(
            r"(?:статус|статус документа)\s*[:\-–—]\s*(.+)",
            line,
            flags=re.IGNORECASE,
        )

        if inline_match:
            value = _normalize_line(
                inline_match.group(1)
            )

            if value in KNOWN_STATUSES:
                return KNOWN_STATUSES[value]

        if normalized not in {
            "статус",
            "статус документа",
            "информация о статусе документа",
        }:
            continue

        for candidate in lines[
            index + 1:index + 4
        ]:
            candidate_normalized = _normalize_line(
                candidate
            )

            if candidate_normalized in KNOWN_STATUSES:
                return KNOWN_STATUSES[
                    candidate_normalized
                ]

            if candidate_normalized in SERVICE_LABELS:
                continue

    return "Не удалось определить"


def _extract_effective_date(
    full_text: str,
    calendar_published: str,
) -> str:
    """
    Извлекает только подтверждённые сведения
    о вступлении документа в силу.
    """

    lines = _prepare_lines(
        full_text
    )

    calendar_dates = set(
        DATE_PATTERN.findall(
            calendar_published
        )
    )

    # Вариант:
    # «Дата вступления в силу 31.07.2026»
    inline_label_pattern = re.compile(
        r"^дата вступления в силу"
        r"\s*[:\-–—]?\s*"
        r"(.+)$",
        flags=re.IGNORECASE,
    )

    # Формулировка из текста самого документа:
    # «Настоящее решение вступает в силу...»
    body_pattern = re.compile(
        r"^(.*\bвступа(?:ет|ют|л|ла|ло|ли)"
        r"\s+в\s+силу\b.*)$",
        flags=re.IGNORECASE,
    )

    for index, line in enumerate(lines):
        normalized = _normalize_line(
            line
        )

        if _is_service_label(
            normalized
        ):
            continue

        inline_match = inline_label_pattern.match(
            line
        )

        if inline_match:
            value = _clean_text(
                inline_match.group(1)
            )

            if _is_valid_effective_value(
                value=value,
                calendar_dates=calendar_dates,
                explicit_statement=False,
            ):
                return value

        body_match = body_pattern.match(
            line
        )

        if body_match:
            value = _clean_text(
                body_match.group(1)
            )

            if _is_valid_effective_value(
                value=value,
                calendar_dates=calendar_dates,
                explicit_statement=True,
            ):
                return value

        if normalized not in {
            "дата вступления в силу",
            "вступление в силу",
            "сведения о вступлении в силу",
        }:
            continue

        # После заголовка принимаем только строку,
        # похожую на дату или юридическую формулировку.
        for candidate in lines[
            index + 1:index + 4
        ]:
            candidate_normalized = _normalize_line(
                candidate
            )

            if _is_service_label(
                candidate_normalized
            ):
                continue

            if _is_valid_effective_value(
                value=candidate,
                calendar_dates=calendar_dates,
                explicit_statement=False,
            ):
                return candidate

    return "Не удалось подтвердить"


def _is_valid_effective_value(
    value: str,
    calendar_dates: set[str],
    explicit_statement: bool,
) -> bool:
    """Проверяет найденное значение вступления в силу."""

    clean_value = _clean_text(
        value
    )

    normalized = _normalize_line(
        clean_value
    )

    if len(clean_value) < 5:
        return False

    if _is_service_label(normalized):
        return False

    forbidden_markers = (
        "история статусов",
        "добавлен в базу",
        "таможенный календарь",
        "дата добавления",
        "подробная информация",
        "скачать документ",
    )

    if any(
        marker in normalized
        for marker in forbidden_markers
    ):
        return False

    found_dates = set(
        DATE_PATTERN.findall(
            clean_value
        )
    )

    effective_phrases = (
        "вступает в силу",
        "вступил в силу",
        "вступила в силу",
        "вступило в силу",
        "вступили в силу",
        "по истечении",
        "со дня официального опубликования",
        "с даты официального опубликования",
        "с момента опубликования",
    )

    has_effective_phrase = any(
        phrase in normalized
        for phrase in effective_phrases
    )

    # Обычная соседняя строка должна содержать
    # либо дату, либо явную формулировку.
    if not explicit_statement:
        if not found_dates and not has_effective_phrase:
            return False

    # Совпадение только с датой добавления в Alta
    # не является подтверждением вступления в силу.
    if (
        found_dates
        and calendar_dates
        and found_dates.issubset(
            calendar_dates
        )
        and not has_effective_phrase
    ):
        logger.warning(
            "Отброшена дата календаря Alta: %s",
            clean_value,
        )
        return False

    return True


def _is_service_label(
    normalized: str,
) -> bool:
    """Проверяет, является ли строка элементом интерфейса."""

    if normalized in SERVICE_LABELS:
        return True

    return any(
        normalized.startswith(
            f"{label} "
        )
        for label in SERVICE_LABELS
    )


def _build_text_excerpt(
    full_text: str,
    title: str,
    max_chars: int,
) -> str:
    """Готовит ограниченный фрагмент текста для LLM."""

    text = full_text.strip()

    if title and text.startswith(title):
        text = text[
            len(title):
        ].strip()

    if len(text) <= max_chars:
        return text

    shortened = text[:max_chars]

    last_paragraph = shortened.rfind(
        "\n"
    )

    if last_paragraph > max_chars // 2:
        shortened = shortened[
            :last_paragraph
        ]

    return (
        shortened.rstrip()
        + "..."
    )


def _prepare_lines(
    full_text: str,
) -> list[str]:
    """Разделяет текст на очищенные строки."""

    lines: list[str] = []

    for raw_line in full_text.splitlines():
        line = _clean_text(
            raw_line
        )

        if line:
            lines.append(
                line
            )

    return lines


def _normalize_line(
    value: str,
) -> str:
    """Нормализует строку для сравнения."""

    return (
        _clean_text(value)
        .lower()
        .strip(" \t\r\n.:;,-–—")
    )


def _clean_text(
    value: object,
) -> str:
    """Очищает текст."""

    text = html.unescape(
        str(value or "")
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    text = re.sub(
        r"[ \t]+",
        " ",
        text,
    )

    return text.strip()