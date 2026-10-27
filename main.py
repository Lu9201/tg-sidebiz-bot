import os
import asyncio
import threading
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from google import genai

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "989667956"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_INSTRUCTION = (
    "你是一位頂尖的數位商品副業合夥人與自動化架構師。"
    "你的老闆是 Lucas。你的核心任務是協助他打造高價值、省時間、高轉化的數位商品（SOP、指南、模板、提示詞庫）。\n"
    "原則：說話直接切中要點、杜絕廢話套話、擅長市場痛點挖掘、藍海選題、定價策略與直接產出可販售的乾貨內容。\n"
    "排版規範：若給出多個方案或章節，請在方案或章節之間使用明確的分割符號「---DIVIDER---」，方便程式為手機端分段推送。"
)

chat_session = ai_client.chats.create(
    model="gemini-3.8-flash",
    config={"system_instruction": SYSTEM_INSTRUCTION}
)

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("💡 推薦全新藍海選題", callback_data="btn_idea")],
        [InlineKeyboardButton("📑 將當前共識生成完整可售手冊", callback_data="btn_create_product")],
        [InlineKeyboardButton("📢 產出高轉換爆款宣傳文案", callback_data="btn_marketing")],
        [InlineKeyboardButton("🔄 清空上下文 / 開啟新主題", callback_data="btn_reset")]
    ]
    return InlineKeyboardMarkup(keyboard)

def is_authorized(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

def ask_gemini_sync(prompt_text: str) -> str:
    global chat_session
    response = chat_session.send_message(prompt_text)
    return response.text

# 彈性進度維護：每 60 秒主動編輯進度，回報狀態
async def run_with_progress_report(status_message, sync_task, initial_text="🧠 已收到請求，正在深入調研與組織內容..."):
    await status_message.edit_text(initial_text)
    loop = asyncio.get_running_loop()
    task = loop.run_in_executor(None, sync_task)
    
    elapsed = 0
    while not task.done():
        await asyncio.sleep(60)
        elapsed += 60
        if not task.done():
            try:
                mins = elapsed // 60
                await status_message.edit_text(
                    f"⏳ 正在深度構思與撰寫中（已用時 {mins} 分鐘）...\n內容篇幅較大，AI 正在持續產出，請稍候。"
                )
            except Exception:
                pass
                
    result_text = await task
    try:
        await status_message.delete()
    except Exception:
        pass
    return result_text

# 智慧分段傳送（支援方案獨立傳送與長文分段）
async def send_formatted_chunks(message_obj, full_text: str, reply_markup=None):
    # 先檢查是否有自訂分割標記
    if "---DIVIDER---" in full_text:
        parts = [p.strip() for p in full_text.split("---DIVIDER---") if p.strip()]
    else:
        # 依方案標題或段落進行智慧拆分
        parts = [p.strip() for p in re.split(r'\n(?=[#*-]{0,3}\s*(?:方案|選題|章節|題目|\d+\.))', full_text) if p.strip()]
        if len(parts) <= 1:
            # 純長文按 3000 字元長度切分
            parts = [full_text[i:i+3000] for i in range(0, len(full_text), 3000)]

    total = len(parts)
    for idx, part in enumerate(parts):
        is_last = (idx == total - 1)
        if total > 1:
            footer = f"\n\n👉 *（{idx + 1}/{total} 內容完畢）*" if is_last else f"\n\n⏳ *（{idx + 1}/{total} 還有後續內容...）*"
            text_to_send = part + footer
        else:
            text_to_send = part

        if is_last:
            await message_obj.reply_text(text_to_send, reply_markup=reply_markup)
        else:
            await message_obj.reply_text(text_to_send)
            await asyncio.sleep(0.8)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ 未授權存取。")
        return
    await update.message.reply_text(
        "👋 Lucas，副業自動化指揮中心已就緒！\n\n"
        "你可以【直接打字】溝通決策或點選快捷按鈕：",
        reply_markup=get_main_menu()
    )

async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    global chat_session
    chat_session = ai_client.chats.create(
        model="gemini-3.8-flash",
        config={"system_instruction": SYSTEM_INSTRUCTION}
    )
    await update.message.reply_text("🔄 已重置記憶與上下文！", reply_markup=get_main_menu())

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    user_text = update.message.text
    status_msg = await update.message.reply_text("📥 已收到指示，正在啟動決策推演...")

    prompt = (
        f"這是 Lucas 的最新決策與反饋：\n『{user_text}』\n\n"
        "請針對指示進行深入規劃：\n"
        "1. 藍海賽道與受眾痛點調研。\n"
        "2. 親民定價與引流策略。\n"
        "3. 數位商品具體架構。\n"
        "不同板塊或重點方案之間，請務必插入『---DIVIDER---』以利手機排版發送。"
    )

    try:
        result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_sync(prompt))
        await send_formatted_chunks(update.message, result_text, get_main_menu())
    except Exception as e:
        await update.message.reply_text(f"⚠️ 處理時發生異常：{str(e)}", reply_markup=get_main_menu())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_authorized(query.from_user.id):
        await query.edit_message_text("⛔ 未授權存取。")
        return

    data = query.data
    global chat_session

    if data == "btn_reset":
        chat_session = ai_client.chats.create(
            model="gemini-3.8-flash",
            config={"system_instruction": SYSTEM_INSTRUCTION}
        )
        await query.message.reply_text("🔄 已重置對話記憶！", reply_markup=get_main_menu())
        return

    status_msg = await query.message.reply_text("⚡ 指令已接收，正在呼叫 AI 執行...")

    if data == "btn_idea":
        prompt = (
            "請為數位商品（電子手冊/SOP/範本）分析 3 個高價值的藍海選題：\n"
            "要求：核心目標必須是幫受眾『節省大量時間』或『翻倍工作/生活效率』。\n"
            "請將每個選題清楚獨立，每個方案之間請單獨一行輸出『---DIVIDER---』。\n"
            "格式請包含：題目、目標客群痛點、建議售價（美元）、核心章節大綱。"
        )
    elif data == "btn_create_product":
        prompt = (
            "請將我們目前討論確定的方向，生成一份完整、結構嚴謹且含金量極高的『數位手冊內容全本』。\n"
            "要求：\n"
            "1. 點出痛點與能為讀者省下的具體時間。\n"
            "2. 步驟附帶可直接套用的實戰 Prompt 或操作 SOP。\n"
            "3. 確保可直接複製至 Gumroad 販售。\n"
            "每個核心章節之間請單獨一行輸出『---DIVIDER---』。"
        )
    elif data == "btn_marketing":
        prompt = (
            "請依據當前的數位商品，撰寫 2 則用於 Threads / X 的高轉化宣傳貼文：\n"
            "貼文 1：痛點戳心切入（沒時間、低效、瞎忙）。\n"
            "貼文 2：成果展示切入（如何用一套流程省下 80% 時間）。\n"
            "兩篇貼文之間請單獨一行輸出『---DIVIDER---』。"
        )
    else:
        prompt = "請向我報告當前副業推進狀態。"

    try:
        result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_sync(prompt))
        await send_formatted_chunks(query.message, result_text, get_main_menu())
    except Exception as e:
        await query.message.reply_text(f"⚠️ 處理時發生異常：{str(e)}", reply_markup=get_main_menu())

def main():
    threading.Thread(target=run_http_server, daemon=True).start()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    print("副業自動化指揮中心運行中...")
    app.run_polling()

if __name__ == "__main__":
    main()
