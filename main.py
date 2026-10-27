import os
import asyncio
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from google import genai

# 環境變數設定
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "989667956"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 初始化 Gemini Client
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# 對話歷史暫存（讓 AI 聽得懂上下文）
conversation_history = []

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

def call_gemini(prompt: str) -> str:
    global conversation_history
    # 紀錄上下文
    conversation_history.append({"role": "user", "parts": [{"text": prompt}]})
    if len(conversation_history) > 10:
        conversation_history = conversation_history[-10:]
        
    response = ai_client.models.generate_content(
        model="gemini-3.8-flash",
        contents=conversation_history
    )
    conversation_history.append({"role": "model", "parts": [{"text": response.text}]})
    return response.text

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
        "👋 Lucas，副業自動化指揮中心已就緒！\n你可以直接點選下方按鈕，或『直接打字』給我任何方向建議與指示：",
        reply_markup=get_main_menu()
    )

# 處理你輸入的自訂文字指令（做決策、給回饋）
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    user_text = update.message.text
    status_msg = await update.message.reply_text("🧠 正在思考並依據你的決策進行規劃...")

    prompt = (
        f"你是我的副業專案經理與 AI 執行助手。我的最新指令是：\n『{user_text}』\n\n"
        "請針對我的要求進行深度分析：\n"
        "1. 市場藍海與受眾絕對痛點評估（為什麼他們非買不可）。\n"
        "2. 降價後的最優定價策略（例如 $9 ~ $19 衝量階段）。\n"
        "3. 依據此方向，輸出該數位商品的詳細章節大綱與製作方案。"
    )

    loop = asyncio.get_running_loop()
    result_text = await loop.run_in_executor(None, call_gemini, prompt)
    await status_msg.delete()
    await send_long_message(update.message, result_text, get_main_menu())

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
            status_msg = await query.message.reply_text("✍️ 正在依據目前討論的方向生成數位商品實戰指南草稿...")
            prompt = (
                "請依據我們剛才選定的方向（內容一魚多吃 / 提示詞鏈 / 提升效率數位手冊），"
                "撰寫一份字數約 1200 字、含金量極高的實用手冊內容草稿。\n"
                "架構要求：\n"
                "1. 核心邏輯與價值省時試算\n"
                "2. 實戰 Prompt 模板（讀者可直接複製貼上套用）\n"
                "3. 跨平台發布的工作流步驟（SOP）\n"
                "避開套話，以立刻能用的乾貨呈現。"
            )
            loop = asyncio.get_running_loop()
            result_text = await loop.run_in_executor(None, call_gemini, prompt)
            await status_msg.delete()
            await send_long_message(query.message, result_text, get_main_menu())

        elif data == "btn_marketing":
            status_msg = await query.message.reply_text("✍️ 正在產出適用於 Threads / X 的高轉換引流貼文...")
            prompt = (
                "請依據我們正在製作的數位商品，撰寫 2 篇社群高轉換貼文：\n"
                "貼文 1（痛點切入）：針對沒時間創作、產出效率低下的創作者/上班族。\n"
                "貼文 2（成果展示）：說明如何用一套流程將產出效率提升 5 倍。\n"
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
    # 新增：接收任意文字訊息
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    print("指揮中心運行中...")
    app.run_polling()

if __name__ == "__main__":
    main()
