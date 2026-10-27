import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from google import genai

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "989667956"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("💡 今日推薦數位商品選題", callback_data="btn_idea")],
        [InlineKeyboardButton("📑 生成數位商品完整草稿", callback_data="btn_create_product")],
        [InlineKeyboardButton("📢 產出社群引流與宣傳文案", callback_data="btn_marketing")]
    ]
    return InlineKeyboardMarkup(keyboard)

def is_authorized(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ 未授權存取。")
        return
    await update.message.reply_text(
        "👋 Lucas，副業自動化指揮中心已就緒！請選擇要執行的任務：",
        reply_markup=get_main_menu()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ 未授權存取。")
        return

    data = query.data

    if data == "btn_idea":
        await query.edit_message_text("🔍 正在分析高價值、幫使用者省時的數位商品題目...")
        prompt = (
            "請為數位商品（電子書/SOP/範本手冊）構思 3 個高價值選題。"
            "要求：核心目標是幫受眾『節省時間』或『提高工作/生活效率』，"
            "且是能馬上落地的乾貨。請包含：題目、受眾痛點、預期定價（美元）、核心章節大綱。"
        )
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        await query.message.reply_text(response.text, reply_markup=get_main_menu())

    elif data == "btn_create_product":
        await query.edit_message_text("✍️ 正在生成《高效個人知識庫與自動化 SOP》迷你實戰指南草稿...")
        prompt = (
            "請撰寫一份字數約 1200 字的迷你實用手冊：《30分鐘打造個人自動化工作流指南》。"
            "內容要極度實用、條理分明、避免廢話，直接給出工具選型、操作步驟與示範，"
            "讓讀者看完即可直接套用並省下工作時間。"
        )
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        await query.message.reply_text(response.text, reply_markup=get_main_menu())

    elif data == "btn_marketing":
        await query.edit_message_text("✍️ 正在產出適用於 Threads / X 的高互動引流貼文...")
        prompt = (
            "請依據《30分鐘打造個人自動化工作流指南》這款數位商品，"
            "撰寫 2 篇 Threads 爆款鉤子（Hook）貼文："
            "1. 一篇以痛點切入（每天加班/瑣事太多）。"
            "2. 一篇以成果展示切入（如何用自動化解放時間）。"
            "末尾附上引導購買數位商品的行動呼籲（CTA）。"
        )
        response = ai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        await query.message.reply_text(response.text, reply_markup=get_main_menu())

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("指揮中心運行中...")
    app.run_polling()

if __name__ == "__main__":
    main()
