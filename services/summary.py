def build_summary(data: dict) -> str:
    return (
        "✅ Информация по поставке:\n\n"
        f"🌍 Страна: {data['country']}\n"
        f"🏢 Получатель: {data['company_type']}\n"
        f"📦 Товар: {data['product']}"
    )


def build_llm_request(data: dict) -> str:
    return (
        "Проведи предварительный анализ поставки.\n\n"
        f"Страна отправления: {data['country']}\n"
        f"Тип получателя: {data['company_type']}\n"
        f"Товар: {data['product']}\n\n"
        "Не придумывай код ТН ВЭД, ставки или требования. "
        "Определи, каких данных и документов не хватает, "
        "какие предварительные риски видны и что нужно сделать дальше."
    )