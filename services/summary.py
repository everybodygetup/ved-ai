def build_summary(data: dict) -> str:
    return f"""
✅ Спасибо!

Вот информация по вашей поставке:

🌍 Страна: {data['country']}

🏢 Получатель: {data['company_type']}

📦 Товар: {data['product']}
"""