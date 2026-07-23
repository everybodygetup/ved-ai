import asyncio
import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Final
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag


logger = logging.getLogger(__name__)


ALTA_BASE_URL: Final[str] = "https://www.alta.ru"
ALTA_TAMDOC_URL: Final[str] = "https://www.alta.ru/tamdoc/"

# Москва всегда используется как UTC+3.
# Так код не зависит от установленной базы tzdata.
MOSCOW_TIMEZONE: Final[timezone] = timezone(
    timedelta(hours=3)
)

REQUEST_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/xml;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
    "Referer": ALTA_TAMDOC_URL,
    "Connection": "close",
}


# Возможные названия календарных разделов.
# Используются, чтобы остановиться перед следующим разделом
# и не захватить посторонние документы страницы.
SECTION_MARKER_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^(?:"
    r"добавлен(?:о|ы)? в базу|"
    r"опубликован(?:о|ы)?(?: в интернете)?|"
    r"подписан(?:о|ы)?|"
    r"принят(?:о|ы)?|"
    r"дата вступления в силу|"
    r"вступил(?:а|о|и)? в силу|"
    r"утратил(?:а|о|и)? силу(?: с)?|"
    r"окончание срока действия(?: с)?|"
    r"начало действия(?: с)?"
    r")\s+\d{2}\.\d{2}\.\d{4}$",
    flags=re.IGNORECASE,
)


# Ссылка настоящего документа выглядит примерно так:
# /tamdoc/26r00117/
#
# При этом исключаются календарные ссылки:
# /tamdoc/2026_07_23/
DOCUMENT_PATH_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^/tamdoc/(?!\d{4}_\d{2}_\d{2}/?$)[^/?#]+/?$",
    flags=re.IGNORECASE,
)


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
    Получает документы только из точного раздела:

    «Добавлен в базу ДД.ММ.ГГГГ».

    По умолчанию проверяется текущая дата по Москве.
    """

    if limit <= 0:
        return []

    calendar_date = (
        target_date
        or datetime.now(MOSCOW_TIMEZONE).date()
    )

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
    """Формирует ссылку на календарь за конкретный день."""

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
    Извлекает ссылки исключительно из нужного
    календарного блока.
    """

    soup = BeautifulSoup(
        page_content,
        "html.parser",
    )

    located = _locate_added_section(
        soup=soup,
        calendar_date=calendar_date,
        calendar_url=calendar_url,
    )

    if located is None:
        logger.info(
            "Точный блок «Добавлен в базу %s» "
            "не найден: %s",
            calendar_date.strftime("%d.%m.%Y"),
            calendar_url,
        )
        return []

    marker, container = located

    anchors = _collect_document_anchors(
        marker=marker,
        container=container,
        calendar_url=calendar_url,
    )

    documents: list[AltaDocument] = []
    seen_links: set[str] = set()

    for anchor in anchors:
        href = str(
            anchor.get("href") or ""
        ).strip()

        link = _normalize_url(
            urljoin(
                ALTA_BASE_URL,
                href,
            )
        )

        if not link:
            continue

        if link in seen_links:
            continue

        title = _clean_text(
            anchor.get_text(
                " ",
                strip=True,
            )
        )

        # Отбрасываем пустые и служебные подписи.
        if len(title) < 8:
            continue

        seen_links.add(link)

        summary = _extract_document_summary(
            link_element=anchor,
            section_container=container,
            title=title,
            calendar_url=calendar_url,
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

    logger.info(
        "Из точного блока «Добавлен в базу» "
        "извлечено документов: %s",
        len(documents),
    )

    for document in documents:
        logger.info(
            "Документ календаря: %s | %s",
            document.title,
            document.link,
        )

    return documents


def _locate_added_section(
    soup: BeautifulSoup,
    calendar_date: date,
    calendar_url: str,
) -> tuple[Tag, Tag] | None:
    """
    Находит точную надпись «Добавлен в базу ДД.ММ.ГГГГ»
    и минимальный HTML-контейнер с её документами.
    """

    expected = (
        "добавлен в базу "
        f"{calendar_date:%d.%m.%Y}"
    )

    candidates: list[Tag] = []

    for tag in soup.find_all(True):
        text = _normalized_lower_text(tag)

        if text != expected:
            continue

        # Иногда один и тот же текст содержат:
        # span, div и несколько родительских блоков.
        # Оставляем самый узкий элемент.
        has_same_text_child = any(
            isinstance(child, Tag)
            and _normalized_lower_text(child) == expected
            for child in tag.find_all(
                recursive=False
            )
        )

        if not has_same_text_child:
            candidates.append(tag)

    candidates.sort(
        key=lambda tag: len(
            tag.find_all(True)
        )
    )

    located_sections: list[
        tuple[int, Tag, Tag]
    ] = []

    for marker in candidates:
        container = _find_section_container(
            marker=marker,
            expected_marker=expected,
            calendar_url=calendar_url,
        )

        if container is None:
            continue

        anchors = _collect_document_anchors(
            marker=marker,
            container=container,
            calendar_url=calendar_url,
        )

        if not anchors:
            continue

        located_sections.append(
            (
                len(
                    container.find_all(True)
                ),
                marker,
                container,
            )
        )

    if not located_sections:
        return None

    # Берём самый маленький валидный контейнер.
    # Это не позволяет захватить общий фон страницы.
    _, marker, container = min(
        located_sections,
        key=lambda item: item[0],
    )

    logger.info(
        "Найден блок календаря Alta: "
        "tag=%s, classes=%s",
        container.name,
        container.get("class"),
    )

    return marker, container


def _find_section_container(
    marker: Tag,
    expected_marker: str,
    calendar_url: str,
) -> Tag | None:
    """
    Поднимается от текста заголовка к ближайшему
    контейнеру, содержащему документы этого события.
    """

    current: Tag | None = marker

    for _ in range(12):
        if current is None:
            break

        marker_texts = (
            _find_section_marker_texts(
                current
            )
        )

        document_links: set[str] = set()

        for anchor in current.find_all(
            "a",
            href=True,
        ):
            href = str(
                anchor.get("href") or ""
            ).strip()

            link = _normalize_url(
                urljoin(
                    ALTA_BASE_URL,
                    href,
                )
            )

            if _is_document_link(
                link=link,
                calendar_url=calendar_url,
            ):
                document_links.add(link)

        # Валидный контейнер:
        # 1. содержит хотя бы один документ;
        # 2. содержит разумное количество ссылок;
        # 3. содержит только наш календарный заголовок;
        # 4. не содержит другие разделы страницы.
        if (
            1 <= len(document_links) <= 20
            and marker_texts == {
                expected_marker
            }
        ):
            return current

        parent = current.parent

        current = (
            parent
            if isinstance(parent, Tag)
            else None
        )

    return None


def _find_section_marker_texts(
    container: Tag,
) -> set[str]:
    """
    Находит календарные заголовки внутри контейнера.

    Например:
    - добавлен в базу 23.07.2026;
    - опубликован в интернете 23.07.2026;
    - дата вступления в силу 23.07.2026.
    """

    result: set[str] = set()

    for tag in container.find_all(True):
        # Большой родитель содержит весь текст блока,
        # поэтому рассматриваем только компактные теги.
        if len(tag.find_all(True)) > 8:
            continue

        text = _normalized_lower_text(
            tag
        )

        if SECTION_MARKER_PATTERN.fullmatch(
            text
        ):
            result.add(text)

    own_text = _normalized_lower_text(
        container
    )

    if (
        len(container.find_all(True)) <= 8
        and SECTION_MARKER_PATTERN.fullmatch(
            own_text
        )
    ):
        result.add(own_text)

    return result


def _collect_document_anchors(
    marker: Tag,
    container: Tag,
    calendar_url: str,
) -> list[Tag]:
    """
    Собирает ссылки, расположенные только после
    заголовка внутри выбранного контейнера.
    """

    anchors: list[Tag] = []
    seen_links: set[str] = set()

    started = False

    for element in container.descendants:
        if element is marker:
            started = True
            continue

        if not started:
            continue

        if not isinstance(element, Tag):
            continue

        # Если внутри контейнера начался следующий
        # календарный раздел — прекращаем чтение.
        if (
            element is not marker
            and len(
                element.find_all(True)
            ) <= 8
        ):
            element_text = (
                _normalized_lower_text(
                    element
                )
            )

            if SECTION_MARKER_PATTERN.fullmatch(
                element_text
            ):
                break

        if element.name != "a":
            continue

        href = str(
            element.get("href") or ""
        ).strip()

        link = _normalize_url(
            urljoin(
                ALTA_BASE_URL,
                href,
            )
        )

        if not _is_document_link(
            link=link,
            calendar_url=calendar_url,
        ):
            continue

        if link in seen_links:
            continue

        seen_links.add(link)
        anchors.append(element)

    return anchors


def _is_document_link(
    link: str,
    calendar_url: str,
) -> bool:
    """
    Проверяет, что ссылка ведёт на документ Alta,
    а не на календарь, поиск или внешний сайт.
    """

    normalized_link = _normalize_url(
        link
    )

    normalized_calendar = _normalize_url(
        calendar_url
    )

    if not normalized_link:
        return False

    if normalized_link == normalized_calendar:
        return False

    parsed = urlparse(
        normalized_link
    )

    if parsed.netloc and parsed.netloc not in {
        "alta.ru",
        "www.alta.ru",
    }:
        return False

    return bool(
        DOCUMENT_PATH_PATTERN.fullmatch(
            parsed.path
        )
    )


def _extract_document_summary(
    link_element: Tag,
    section_container: Tag,
    title: str,
    calendar_url: str,
) -> str:
    """
    Извлекает краткое описание из ближайшей
    карточки конкретного документа.
    """

    current = link_element.parent
    best_text = ""

    for _ in range(7):
        if not isinstance(current, Tag):
            break

        if current is section_container:
            break

        document_anchors = []

        for anchor in current.find_all(
            "a",
            href=True,
        ):
            href = str(
                anchor.get("href") or ""
            ).strip()

            link = urljoin(
                ALTA_BASE_URL,
                href,
            )

            if _is_document_link(
                link=link,
                calendar_url=calendar_url,
            ):
                document_anchors.append(
                    anchor
                )

        text = _clean_text(
            current.get_text(
                " ",
                strip=True,
            )
        )

        # Карточка должна содержать только одну
        # ссылку на нормативный документ.
        if (
            len(document_anchors) == 1
            and len(text) > len(title)
        ):
            best_text = text
            break

        parent = current.parent

        current = (
            parent
            if isinstance(parent, Tag)
            else None
        )

    if not best_text:
        # На некоторых страницах описание может идти
        # отдельным соседним элементом.
        parent = link_element.parent

        if isinstance(parent, Tag):
            sibling = parent.find_next_sibling()

            if isinstance(sibling, Tag):
                sibling_text = _clean_text(
                    sibling.get_text(
                        " ",
                        strip=True,
                    )
                )

                if (
                    sibling_text
                    and not SECTION_MARKER_PATTERN.fullmatch(
                        sibling_text.lower()
                    )
                ):
                    best_text = sibling_text

    if not best_text:
        return ""

    if best_text.startswith(title):
        best_text = best_text[
            len(title):
        ].strip(" ;—–-:")

    if best_text == title:
        return ""

    if len(best_text) > 700:
        best_text = (
            best_text[:697].rstrip()
            + "..."
        )

    return best_text


async def _download_page(
    page_url: str,
) -> bytes:
    """
    Скачивает страницу Alta.

    Сначала пробует системные настройки сети,
    затем прямое соединение без системного прокси.
    """

    timeout = httpx.Timeout(
        connect=15.0,
        read=35.0,
        write=20.0,
        pool=15.0,
    )

    last_error: Exception | None = None

    for trust_env in (
        True,
        False,
    ):
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


def _normalize_url(
    value: str,
) -> str:
    """Удаляет fragment и нормализует адрес."""

    if not value:
        return ""

    parsed = urlparse(
        value
    )

    path = parsed.path or "/"

    return parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=path,
        fragment="",
    ).geturl()


def _normalized_lower_text(
    tag: Tag,
) -> str:
    """Возвращает очищенный текст тега в нижнем регистре."""

    return _clean_text(
        tag.get_text(
            " ",
            strip=True,
        )
    ).lower()


def _clean_text(
    value: object,
) -> str:
    """Удаляет HTML-сущности и лишние пробелы."""

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