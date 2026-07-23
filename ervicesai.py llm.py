[1mdiff --git a/handlers/autoparts.py b/handlers/autoparts.py[m
[1mindex 3b0624c..f72a30f 100644[m
[1m--- a/handlers/autoparts.py[m
[1m+++ b/handlers/autoparts.py[m
[36m@@ -3,6 +3,9 @@[m [mfrom aiogram.types import Message[m
 from aiogram.fsm.context import FSMContext[m
 [m
 from states.import_state import ImportState[m
[32m+[m[32mfrom keyboards.company_type import company_keyboard[m
[32m+[m[32mfrom services.summary import build_summary[m
[32m+[m
 [m
 from data.messages import ([m
     ASK_COUNTRY,[m
[36m@@ -28,7 +31,10 @@[m [masync def process_country(message: Message, state: FSMContext):[m
 [m
     await state.set_state(ImportState.company_type)[m
 [m
[31m-    await message.answer(ASK_COMPANY)[m
[32m+[m[32m    await message.answer([m
[32m+[m[32m    ASK_COMPANY,[m
[32m+[m[32m    reply_markup=company_keyboard,[m
[32m+[m[32m)[m
 [m
 @router.message(ImportState.company_type)[m
 async def process_company(message: Message, state: FSMContext):[m
[36m@@ -46,16 +52,7 @@[m [masync def process_product(message: Message, state: FSMContext):[m
 [m
     data = await state.get_data()[m
 [m
[31m-    await message.answer([m
[31m-    f"""{SUMMARY}[m
[31m-[m
[31m-🌍 Страна: {data["country"]}[m
[31m-[m
[31m-🏢 Получатель: {data["company_type"]}[m
[31m-[m
[31m-📦 Товар: {data["product"]}[m
[31m-"""[m
[31m-)[m
[32m+[m[32m    await message.answer(build_summary(data))[m
 [m
 [m
 async def autoparts_handler(message: Message):[m
