import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from google import genai

# 環境變數設定
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "989667956"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 初始化 Gemini Client
ai_client = genai.Client(api_key=GEMINI_API_KEY)

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
        [InlineKeyboardButton("💡 今日推薦數位商品選題", callback_data="btn_idea")],
        [InlineKeyboardButton("📑 生成數位商品完整草稿", callback_data="btn_create_product")],
        [InlineKeyboardButton("📢 產出社群引流與宣傳文案", callback_data="btn_marketing")]
    ]
    return InlineKeyboardMarkup(keyboard)

def is_authorized(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

# 呼叫 Gemini 的安全同步封裝
def call_gemini(prompt: str) -> str:
    response = ai_client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt
    )
    return response.text

# 處理 Telegram 訊息長度超過 4000 字元的分段發送輔助函數
async def send_long_message(message_obj, text: str, reply_markup=None):
    chunk_size = 3500
    if len(text) <= chunk_size:
        await message_obj.reply_text(text, reply_markup=reply_markup)
    else:
        chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]
        for i, chunk in enumerate(chunks):
            if i == len(chunks) - 1:
                await message_obj.reply_text(chunk, reply_markup=reply_markup)
            else:
                await message_obj.reply_text(chunk)

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

    try:
        if data == "btn_idea":
            status_msg = await query.message.reply_text("🔍 正在分析高價值、幫讀者省時的數位商品題目...")
            prompt = (
                "請為數位商品（電子書/SOP/範本手冊）構思 3 個高價值選題。\n"
                "核心標準：必須能幫受眾『節省時間』或『提高工作與生活效率』，實用性高。\n"
                "請條列列出：題目名稱、核心目標客群痛點、建議定價（美元）、4 個核心實踐章節。"
            )
            loop = asyncio.get_running_loop()
            result_text = await loop.run_in_executor(None, call_gemini, prompt)
            await status_msg.delete()
            await send_long_message(query.message, result_text, get_main_menu())

        elif data == "btn_create_product":
            status_msg = await query.message.reply_text("✍️ 正在生成《高效個人知識庫與自動化 SOP》實戰指南草稿...")
            prompt = (
                "請撰寫一份字數約 1200 字的實戰迷你手冊：《30分鐘打造個人自動化工作流指南》。\n"
                "架構要求：\n"
                "1. 前言：為什麼要自動化，能幫你省下多少時間？\n"
                "2. 核心架構：選型說明（手機/通訊軟體 + 雲端自動化 + AI 大腦）。\n"
                "3. 實作 SOP：3 個立即可套用的自動化場景步驟。\n"
                "4. 避坑指南：新手最常踩的三個雷區。\n"
                "文筆精煉、條理分明，不要無意義的套話。"
            )
            loop = asyncio.get_running_loop()
            result_text = await loop.run_in_executor(None, call_gemini, prompt)
            await status_msg.delete()
            await send_long_message(query.message, result_text, get_main_menu())

        elif data == "btn_marketing":
            status_msg = await query.message.reply_text("✍️ 正在產出適用於 Threads / X 的高轉換引流貼文...")
            prompt = (
                "請依據《30分鐘打造個人自動化工作流指南》這款數位商品，撰寫 2 篇社群高轉換貼文：\n"
                "貼文 1（痛點切入）：針對被重複性瑣事纏身、沒時間做副業的上班族。\n"
                "貼文 2（成果展示）：說明用手機 5 分鐘審核 AI 產出的流程與解放感。\n"
                "每篇請包含吸睛開頭（Hook）、乾貨要點與明確的行動呼籲（CTA）。"
            )
            loop = asyncio.get_running_loop()
            result_text = await loop.run_in_executor(None, call_gemini, prompt)
            await status_msg.delete()
            await send_long_message(query.message, result_text, get_main_menu())

    except Exception as e:
        await query.message.reply_text(f"⚠️ 執行發生異常：{str(e)}", reply_markup=get_main_menu())

def main():
    threading.Thread(target=run_http_server, daemon=True).start()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    print("指揮中心運行中...")
    app.run_polling()

if __name__ == "__main__":
    main()
