import os
import asyncio
import threading
import json
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from google import genai

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "989667956"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GUMROAD_ACCESS_TOKEN = os.environ.get("GUMROAD_ACCESS_TOKEN")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_INSTRUCTION = (
    "你是一位具備實戰商業思維的 AI 副業操盤手與 Agent 架構師。"
    "你的老闆是 Lucas。你的核心任務是協助他打造高價值、省時間、高轉化的數位商品（SOP、模板庫、提示詞手冊）。\n"
    "原則：針對台灣與華語市場，採取親民定價（$3 ~ $7 美元 / 約 NT$99 ~ NT$199）以降低衝動購買門檻；"
    "專注於能『即插即用、馬上省時間』的乾貨內容，拒絕空泛理論。"
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
        [InlineKeyboardButton("📑 生成完整數位手冊草稿", callback_data="btn_draft")],
        [InlineKeyboardButton("🚀 自動建立 Gumroad 商品並取得銷售網址", callback_data="btn_publish_gumroad")],
        [InlineKeyboardButton("📢 產出高轉換爆款推廣貼文", callback_data="btn_marketing")],
        [InlineKeyboardButton("🔄 清空上下文 / 開啟新主題", callback_data="btn_reset")]
    ]
    return InlineKeyboardMarkup(keyboard)

def is_authorized(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

def ask_gemini_sync(prompt_text: str) -> str:
    global chat_session
    response = chat_session.send_message(prompt_text)
    return response.text

# 呼叫 Gumroad API 自動建立數位商品
def create_gumroad_product_sync(name: str, description: str, price_cents: int = 499) -> dict:
    if not GUMROAD_ACCESS_TOKEN:
        return {"success": False, "error": "尚未設定 GUMROAD_ACCESS_TOKEN 環境變數"}
    
    url = "https://api.gumroad.com/v2/products"
    payload = {
        "access_token": GUMROAD_ACCESS_TOKEN,
        "name": name,
        "price": price_cents, # 單位為美分，例如 499 代表 $4.99 美元 (約 NT$150)
        "description": description,
        "custom_permalink": "",
        "require_shipping": "false"
    }
    try:
        res = requests.post(url, data=payload, timeout=20)
        data = res.json()
        if data.get("success"):
            product_url = data["product"]["short_url"]
            edit_url = f"https://app.gumroad.com/products/{data['product']['id']}/edit"
            return {"success": True, "url": product_url, "edit_url": edit_url, "name": name}
        else:
            return {"success": False, "error": data.get("message", "建立商品失敗")}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def run_with_progress_report(status_message, sync_task, initial_text="🧠 正在執行任務..."):
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
                await status_message.edit_text(f"⏳ 任務處理中（已用時 {mins} 分鐘）...")
            except Exception:
                pass
                
    result = await task
    try:
        await status_message.delete()
    except Exception:
        pass
    return result

async def send_formatted_chunks(message_obj, full_text: str, reply_markup=None):
    if "---DIVIDER---" in full_text:
        parts = [p.strip() for p in full_text.split("---DIVIDER---") if p.strip()]
    else:
        parts = [full_text[i:i+3500] for i in range(0, len(full_text), 3500)]

    total = len(parts)
    for idx, part in enumerate(parts):
        is_last = (idx == total - 1)
        if total > 1:
            footer = f"\n\n👉 *（{idx + 1}/{total} 完畢）*" if is_last else f"\n\n⏳ *（{idx + 1}/{total} 待續...）*"
            text_to_send = part + footer
        else:
            text_to_send = part

        if is_last:
            await message_obj.reply_text(text_to_send, reply_markup=reply_markup)
        else:
            await message_obj.reply_text(text_to_send)
            await asyncio.sleep(0.5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ 未授權存取。")
        return
    await update.message.reply_text(
        "👋 Lucas，副業 Agent 指揮中心已就緒！\n我能直接幫你構思、撰寫手冊並【全自動上架 Gumroad 產生銷售連結】。\n\n你可以直接打字交代決策，或點選下方按鈕：",
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
    await update.message.reply_text("🔄 已重置記憶！", reply_markup=get_main_menu())

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    user_text = update.message.text
    status_msg = await update.message.reply_text("📥 已收到指示，Agent 正在規劃...")

    prompt = (
        f"這是 Lucas 的最新決策：\n『{user_text}』\n\n"
        "請針對指示深入分析（考量台灣市場消費習慣、低阻力親民定價與高痛點解決方案）。\n"
        "不同方案或板塊之間請加上『---DIVIDER---』方便分段發送。"
    )

    try:
        result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_sync(prompt))
        await send_formatted_chunks(update.message, result_text, get_main_menu())
    except Exception as e:
        await update.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

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
        await query.message.reply_text("🔄 已重置記憶！", reply_markup=get_main_menu())
        return

    if data == "btn_idea":
        status_msg = await query.message.reply_text("🔍 Agent 正在篩選親民定價且痛點極高的藍海題目...")
        prompt = (
            "請為台灣與華語市場推薦 3 個高轉化數位商品選題（定價 NT$99 ~ NT$199 / $4.99 美元）：\n"
            "重點：能幫受眾立即省下重複時間、即插即用（如提示詞外掛庫、自動化模板）。\n"
            "方案之間請單獨一行輸出『---DIVIDER---』。\n"
            "格式請包含：題目、目標客群痛點、建議售價、核心章節/內容清單。"
        )
        try:
            result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_sync(prompt))
            await send_formatted_chunks(query.message, result_text, get_main_menu())
        except Exception as e:
            await query.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

    elif data == "btn_draft":
        status_msg = await query.message.reply_text("✍️ 正在產出完整實用手冊內容...")
        prompt = (
            "請將我們目前選定的方向，直接生成一份完整且乾貨滿滿的數位指南內容（Markdown 格式）。\n"
            "包含：痛點效益試算、即插即用 Prompt/模板、操作步驟、常見避坑指南。\n"
            "章節之間請加上『---DIVIDER---』。"
        )
        try:
            result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_sync(prompt))
            await send_formatted_chunks(query.message, result_text, get_main_menu())
        except Exception as e:
            await query.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

    elif data == "btn_publish_gumroad":
        status_msg = await query.message.reply_text("🚀 Agent 正在呼叫 Gumroad API 自動建立商品...")
        
        # 1. 先由 Gemini 總結出精準的商品標題與銷售頁面文案
        def agent_publish_flow():
            prompt = (
                "請依據我們目前的數位商品內容，輸出純 JSON 格式（不要有任何 markdown 標籤或額外文字）：\n"
                "{\n"
                '  "name": "極度吸睛的商品名稱（40字內）",\n'
                '  "description": "簡短痛點打擊、這份手冊包含什麼、能省下多少時間的銷售文案（約 300 字）"\n'
                "}"
            )
            raw_json = ask_gemini_sync(prompt).strip()
            if raw_json.startswith("```json"):
                raw_json = raw_json[7:-3].strip()
            elif raw_json.startswith("```"):
                raw_json = raw_json[3:-3].strip()
            
            try:
                info = json.loads(raw_json)
            except Exception:
                info = {
                    "name": "高效內容自動化與變現實戰指南",
                    "description": "立即省下 80% 創作時間，包含 5 套即插即用提示詞與工作流。"
                }
            
            # 2. 自動調用 Gumroad API 建立商品
            return create_gumroad_product_sync(
                name=info.get("name", "高效數位工作手冊"),
                description=info.get("description", "即插即用的數位指南"),
                price_cents=499 # $4.99 美元 (約 NT$150)
            )

        try:
            res = await run_with_progress_report(status_msg, agent_publish_flow, "🚀 正在串接 Gumroad 上架商品中...")
            if res.get("success"):
                reply = (
                    f"🎉 **數位商品已全自動上架完成！**\n\n"
                    f"📦 **商品名稱**：{res['name']}\n"
                    f"💲 **設定售價**：$4.99 美元（約 NT$150，低阻力衝量定價）\n\n"
                    f"🔗 **前台專屬購買網址（發給客戶/社群引流）**：\n{res['url']}\n\n"
                    f"🛠 **後台編輯/上傳附件連結**：\n{res['edit_url']}"
                )
            else:
                reply = f"❌ 上架失敗：{res.get('error')}"
            await query.message.reply_text(reply, reply_markup=get_main_menu())
        except Exception as e:
            await query.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

    elif data == "btn_marketing":
        status_msg = await query.message.reply_text("✍️ 正在產出高轉換爆款推廣文案...")
        prompt = (
            "請為我們目前上架的數位商品，撰寫 2 則用於 Threads / X 的高轉化宣傳貼文：\n"
            "貼文 1：痛點戳心切入（沒時間、低效、瞎忙）。\n"
            "貼文 2：成果展示切入（如何用一套流程省下 80% 時間）。\n"
            "文末附上引導購買的行動呼籲（CTA）。兩篇貼文之間輸出『---DIVIDER---』。"
        )
        try:
            result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_sync(prompt))
            await send_formatted_chunks(query.message, result_text, get_main_menu())
        except Exception as e:
            await query.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

def main():
    threading.Thread(target=run_http_server, daemon=True).start()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    print("副業 Agent 自動化指揮中心運作中...")
    app.run_polling()

if __name__ == "__main__":
    main()
