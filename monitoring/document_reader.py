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
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
}


@dataclass(slots=True, frozen=True)
class AltaDocumentDetails:
    """Сведения, извлечённые со страницы документа."""

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
    """
    Загружает страницы нескольких документов.

    Одновременно открывается не более трёх страниц,
    чтобы не создавать лишнюю нагрузку на Alta.
    """

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
                effective_date="Не удалось определить",
                text_excerpt=document.summary,
                extraction_error=(
                    f"{type(error).__name__}: {error}"
                ),
            )

    tasks = [
        load_one(document)
        for document in documents[:max_documents]
    ]

    return list(
        await asyncio.gather(*tasks)
    )


async def fetch_document_details(
    document: AltaDocument,
    max_text_chars: int = 3500,
) -> AltaDocumentDetails:
    """Открывает страницу одного документа Alta."""

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

    full_text = _extract_main_text(soup)

    status = _extract_status(full_text)

    effective_date = _extract_effective_date(
        full_text
    )

    excerpt = _build_text_excerpt(
        full_text=full_text,
        title=title,
        max_chars=max_text_chars,
    )

    logger.info(
        "Документ Alta прочитан: url=%s, "
        "символов=%s, статус=%r, вступление=%r",
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
    """Скачивает страницу документа с повторными попытками."""

    timeout = httpx.Timeout(
        connect=15.0,
        read=35.0,
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
    """Получает основной заголовок документа."""

    heading = soup.find("h1")

    if heading is not None:
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
    """Извлекает видимый текст основной части страницы."""

    for unwanted in soup.find_all(
        [
            "script",
            "style",
            "noscript",
            "svg",
            "form",
            "iframe",
        ]
    ):
        unwanted.decompose()

    candidates: list[Tag] = []

    for selector in (
        "main",
        "article",
        "[role='main']",
        ".content",
        ".page-content",
        ".b-text",
    ):
        element = soup.select_one(selector)

        if isinstance(element, Tag):
            candidates.append(element)

    if isinstance(soup.body, Tag):
        candidates.append(soup.body)

    if not candidates:
        return ""

    # Выбираем наиболее содержательный контейнер.
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
        line = _clean_text(raw_line)

        if not line:
            continue

        if line == previous_line:
            continue

        previous_line = line
        lines.append(line)

    return "\n".join(lines)


def _extract_status(
    full_text: str,
) -> str:
    """Ищет только явную отметку статуса документа."""

    known_statuses = {
        "документ действует": "Документ действует",
        "документ не действует": "Документ не действует",
        "документ частично не действует": (
            "Документ частично не действует"
        ),
        "статус не определен": "Статус не определён",
        "статус не определён": "Статус не определён",
    }

    for raw_line in full_text.splitlines():
        line = _clean_text(raw_line)
        normalized = line.lower().strip(" .:;-")

        for marker, status in known_statuses.items():
            if normalized == marker:
                return status

    return "Не удалось определить"

def _extract_effective_date(
    full_text: str,
) -> str:
    """Ищет сведения о вступлении документа в силу."""

    patterns = (
        (
            r"дата вступления в силу\s*[:\-]?\s*"
            r"([^\n]{1,180})"
        ),
        (
            r"(вступает в силу[^\n]{1,220})"
        ),
        (
            r"(вступил в силу[^\n]{1,220})"
        ),
        (
            r"(вступила в силу[^\n]{1,220})"
        ),
        (
            r"(вступило в силу[^\n]{1,220})"
        ),
    )

    for pattern in patterns:
        match = re.search(
            pattern,
            full_text,
            flags=re.IGNORECASE,
        )

        if match:
            value = _clean_text(
                match.group(1)
            )

            if value:
                return value

    return "Не указано"


def _build_text_excerpt(
    full_text: str,
    title: str,
    max_chars: int,
) -> str:
    """Подготавливает ограниченный фрагмент для LLM."""

    text = full_text.strip()

    if title and text.startswith(title):
        text = text[len(title):].strip()

    if len(text) <= max_chars:
        return text

    shortened = text[:max_chars]

    last_paragraph = shortened.rfind("\n")

    if last_paragraph > max_chars // 2:
        shortened = shortened[:last_paragraph]

    return shortened.rstrip() + "..."


def _clean_text(
    value: object,
) -> str:
    """Очищает текст от HTML и лишних пробелов."""

    text = html.unescape(
        str(value or "")
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    return re.sub(
        r"[ \t]+",
        " ",
        text,
    ).strip()