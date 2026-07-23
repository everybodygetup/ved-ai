import asyncio
import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag


logger = logging.getLogger(__name__)


ALTA_BASE_URL: Final[str] = "https://www.alta.ru"
ALTA_TAMDOC_URL: Final[str] = "https://www.alta.ru/tamdoc/"

MOSCOW_TIMEZONE: Final[ZoneInfo] = ZoneInfo(
    "Europe/Moscow"
)

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
    "Referer": ALTA_TAMDOC_URL,
}


@dataclass(slots=True, frozen=True)
class AltaDocument:
    """Документ из Таможенного календаря Alta."""

    source_id: str
    title: str
    link: str
    published: str
    summary: str
    calendar_link: str = ""


async def fetch_alta_documents(
    limit: int = 30,
    target_date: date | None = None,
) -> list[AltaDocument]:
    """
    Получает документы из раздела «Добавлен в базу»
    Таможенного календаря Alta.

    По умолчанию используется текущая дата по Москве.
    """

    if limit <= 0:
        return []

    calendar_date = target_date or datetime.now(
        MOSCOW_TIMEZONE
    ).date()

    calendar_url = build_calendar_url(
        calendar_date
    )

    logger.info(
        "Проверяю Таможенный календарь Alta: %s",
        calendar_url,
    )

    page_content = await _download_page(
        calendar_url
    )

    documents = _parse_added_documents(
        page_content=page_content,
        calendar_url=calendar_url,
        calendar_date=calendar_date,
    )

    logger.info(
        "В календаре Alta за %s найдено документов "
        "«Добавлен в базу»: %s",
        calendar_date.strftime("%d.%m.%Y"),
        len(documents),
    )

    return documents[:limit]


def build_calendar_url(
    calendar_date: date,
) -> str:
    """Формирует ссылку на выбранный день календаря."""

    return (
        f"{ALTA_TAMDOC_URL}"
        f"{calendar_date:%Y_%m_%d}/"
    )


def _parse_added_documents(
    page_content: bytes,
    calendar_url: str,
    calendar_date: date,
) -> list[AltaDocument]:
    """
    Находит раздел «Добавлен в базу»
    и извлекает документы до следующего заголовка.
    """

    soup = BeautifulSoup(
        page_content,
        "html.parser",
    )

    added_heading = _find_added_heading(soup)

    if added_heading is None:
        logger.info(
            "Раздел «Добавлен в базу» отсутствует: %s",
            calendar_url,
        )
        return []

    documents: list[AltaDocument] = []
    seen_links: set[str] = set()

    for element in added_heading.next_elements:
        if element is added_heading:
            continue

        # Следующий заголовок означает конец нужного раздела.
        if (
            isinstance(element, Tag)
            and element.name
            in {"h1", "h2", "h3", "h4"}
        ):
            break

        if not (
            isinstance(element, Tag)
            and element.name == "a"
        ):
            continue

        href = str(
            element.get("href") or ""
        ).strip()

        if not href:
            continue

        link = urljoin(
            ALTA_BASE_URL,
            href,
        )

        if not _is_document_link(
            link=link,
            calendar_url=calendar_url,
        ):
            continue

        if link in seen_links:
            continue

        title = _clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        if not title:
            continue

        seen_links.add(link)

        summary = _extract_document_summary(
            link_element=element,
            title=title,
        )

        documents.append(
            AltaDocument(
                source_id=link,
                title=title,
                link=link,
                published=(
                    "Добавлен в базу "
                    f"{calendar_date:%d.%m.%Y}"
                ),
                summary=summary,
                calendar_link=calendar_url,
            )
        )

    return documents


def _find_added_heading(
    soup: BeautifulSoup,
) -> Tag | None:
    """Ищет заголовок «Добавлен в базу»."""

    for heading in soup.find_all(
        ["h1", "h2", "h3", "h4"]
    ):
        heading_text = _clean_text(
            heading.get_text(
                " ",
                strip=True,
            )
        ).lower()

        if heading_text.startswith(
            "добавлен в базу"
        ):
            return heading

    return None


def _is_document_link(
    link: str,
    calendar_url: str,
) -> bool:
    """Отделяет ссылки документов от служебных ссылок."""

    normalized_link = link.split("#", maxsplit=1)[0]
    normalized_calendar = calendar_url.rstrip("/") + "/"

    if (
        normalized_link.rstrip("/") + "/"
        == normalized_calendar
    ):
        return False

    path = urlparse(
        normalized_link
    ).path

    if not path.startswith("/tamdoc/"):
        return False

    # Не принимаем корень, поиск и страницы календарных дат.
    if path.rstrip("/") in {
        "/tamdoc",
        "/tamdoc/search",
    }:
        return False

    if re.fullmatch(
        r"/tamdoc/\d{4}_\d{2}_\d{2}/?",
        path,
    ):
        return False

    return True


def _extract_document_summary(
    link_element: Tag,
    title: str,
) -> str:
    """
    Получает краткое пояснение, расположенное
    рядом с названием документа.
    """

    list_item = link_element.find_parent("li")

    if list_item is None:
        return ""

    item_text = _clean_text(
        list_item.get_text(
            " ",
            strip=True,
        )
    )

    if item_text.startswith(title):
        item_text = item_text[
            len(title):
        ].strip(" ;—–-")

    if item_text == title:
        return ""

    if len(item_text) > 700:
        item_text = (
            item_text[:697].rstrip()
            + "..."
        )

    return item_text


async def _download_page(
    page_url: str,
) -> bytes:
    """Скачивает страницу с повторными попытками."""

    timeout = httpx.Timeout(
        connect=15.0,
        read=30.0,
        write=20.0,
        pool=15.0,
    )

    last_error: Exception | None = None

    # Сначала используем настройки Windows/VPN,
    # затем пробуем прямое соединение.
    for trust_env in (True, False):
        mode_name = (
            "с системными настройками"
            if trust_env
            else "без системного прокси"
        )

        for attempt in range(1, 4):
            try:
                logger.info(
                    "Загрузка календаря Alta: "
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
                        "Alta вернула пустую страницу."
                    )

                logger.info(
                    "Календарь Alta получен: "
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
                    "Ошибка загрузки Alta: "
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
        "Не удалось открыть Таможенный календарь Alta: "
        f"{type(last_error).__name__ if last_error else 'UnknownError'}: "
        f"{last_error or 'причина неизвестна'}"
    )


def _clean_text(
    value: object,
) -> str:
    """Удаляет HTML и лишние пробелы."""

    text = html.unescape(
        str(value or "")
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()