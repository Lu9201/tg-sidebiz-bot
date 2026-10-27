import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from google import genai

# 環境變數
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "989667956"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 初始化 Gemini
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# 系統人設：專屬副業操盤手與數位商品架構師
SYSTEM_INSTRUCTION = (
    "你是一位頂尖的數位商品副業合夥人與自動化架構師。"
    "你的老闆是 Lucas。你的核心任務是協助他打造高價值、省時間、高轉化的數位商品（SOP、指南、模板、提示詞庫）。"
    "原則：說話直接切中要點、杜絕廢話套話、擅長市場痛點挖掘、藍海選題、定價策略與直接產出可販售的乾貨內容。"
)

# 建立全域對話 Session
chat_session = ai_client.chats.create(
    model="gemini-3.8-flash",
    config={"system_instruction": SYSTEM_INSTRUCTION}
)

# 偽裝 HTTP 伺服器供 Render 檢測 Port
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

# 核心同步呼叫封裝
def ask_gemini_sync(prompt_text: str) -> str:
    global chat_session
    response = chat_session.send_message(prompt_text)
    return response.text

# 智慧長文本分片傳送
async def safe_reply(message_obj, text: str, reply_markup=None):
    chunk_size = 3500
    if len(text) <= chunk_size:
        await message_obj.reply_text(text, reply_markup=reply_markup)
    else:
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            if i + chunk_size >= len(text):
                await message_obj.reply_text(chunk, reply_markup=reply_markup)
            else:
                await message_obj.reply_text(chunk)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ 未授權存取。")
        return
    await update.message.reply_text(
        "👋 Lucas，副業自動化指揮中心已就緒！\n\n"
        "你可以隨時【直接傳文字】進行討論、下達指令，或點選下方快捷按鈕：",
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
    await update.message.reply_text("🔄 已重置記憶與上下文，隨時可以開啟全新副業專案！", reply_markup=get_main_menu())

# 文字訊息處理（自然語言對話與決策）
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    user_text = update.message.text
    status_msg = await update.message.reply_text("🧠 正在思考並依據你的決策進行規劃...")

    loop = asyncio.get_running_loop()
    try:
        # 加入 60 秒防超時保護
        reply_content = await asyncio.wait_for(
            loop.run_in_executor(None, ask_gemini_sync, user_text),
            timeout=60.0
        )
        try:
            await status_msg.delete()
        except Exception:
            pass
        await safe_reply(update.message, reply_content, get_main_menu())

    except asyncio.TimeoutError:
        try:
            await status_msg.delete()
        except Exception:
            pass
        await update.message.reply_text("⚠️ 請求逾時，請精簡指令或再試一次。", reply_markup=get_main_menu())
    except Exception as e:
        try:
            await status_msg.delete()
        except Exception:
            pass
        await update.message.reply_text(f"⚠️ 執行異常：{str(e)}", reply_markup=get_main_menu())

# 按鈕回調邏輯
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

    status_msg = await query.message.reply_text("⚡ 正在調度 AI 執行指令...")
    loop = asyncio.get_running_loop()

    if data == "btn_idea":
        prompt = (
            "請為數位商品（電子手冊/SOP/範本）分析 3 個高價值的藍海選題：\n"
            "要求：核心目標必須是幫受眾『節省大量時間』或『翻倍工作/生活效率』。\n"
            "格式請包含：題目、目標客群痛點、建議售價（美元）、核心章節大綱。"
        )
    elif data == "btn_create_product":
        prompt = (
            "請將我們目前討論確定的方向，直接生成一份完整、結構嚴謹且含金量極高的『數位手冊內容全本（Markdown格式）』。\n"
            "要求：\n"
            "1. 開頭點出痛點與能為讀者省下多少小時。\n"
            "2. 步驟必須附帶可直接複製貼上的實戰 Prompt 或具體操作 SOP。\n"
            "3. 確保可以直接打包在 Gumroad 上架販售。"
        )
    elif data == "btn_marketing":
        prompt = (
            "請依據我們目前的數位商品，撰寫 2 則用於 Threads / X 的高轉化爆款推廣貼文：\n"
            "貼文 1：痛點戳心切入（沒時間、低效、瞎忙）。\n"
            "貼文 2：成果展示切入（如何用一套流程省下 80% 時間）。\n"
            "文末附上明確且強烈的行動呼籲（CTA）。"
        )
    else:
        prompt = "請向我報告當前副業推進狀態。"

    try:
        reply_content = await asyncio.wait_for(
            loop.run_in_executor(None, ask_gemini_sync, prompt),
            timeout=60.0
        )
        try:
            await status_msg.delete()
        except Exception:
            pass
        await safe_reply(query.message, reply_content, get_main_menu())
    except asyncio.TimeoutError:
        try:
            await status_msg.delete()
        except Exception:
            pass
        await query.message.reply_text("⚠️ 請求逾時，請重試一次。", reply_markup=get_main_menu())
    except Exception as e:
        try:
            await status_msg.delete()
        except Exception:
            pass
        await query.message.reply_text(f"⚠️ 執行異常：{str(e)}", reply_markup=get_main_menu())

def main():
    threading.Thread(target=run_http_server, daemon=True).start()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    print("副業自動化指揮中心上線運作中...")
    app.run_polling()

if __name__ == "__main__":
    main()
