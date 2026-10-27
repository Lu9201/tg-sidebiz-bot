import os
import asyncio
import threading
import json
import time
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from google import genai

# 環境變數設定
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "989667956"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GUMROAD_ACCESS_TOKEN = os.environ.get("GUMROAD_ACCESS_TOKEN")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_PAGE_ID = os.environ.get("NOTION_PAGE_ID", "406ab074b50c80a291e2c5a073ebc878").replace("-", "")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

SYSTEM_INSTRUCTION = (
    "You are an elite Digital Product Strategist and Automated Business Agent targeting the US/Global market.\n"
    "Your owner is Lucas. Your mission is to conceptualize, write, package, and autonomously publish high-value, "
    "time-saving digital assets (Notion OS templates, plug-and-play prompt systems, and concise SOP checklists) priced at $9.99 USD.\n"
    "Guidelines:\n"
    "1. All product deliverables, descriptions, and SEO keywords must be in professional, crisp, native English.\n"
    "2. All conversational strategy briefings with Lucas must remain in Traditional Chinese (繁體中文).\n"
    "3. Focus strictly on solving tangible pain points for remote workers, freelancers, and solo creators.\n"
    "4. When outputting multiple proposals or long sections, separate them with '---DIVIDER---'."
)

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
        [InlineKeyboardButton("💡 推薦歐美高需求藍海選題", callback_data="btn_idea")],
        [InlineKeyboardButton("🚀 1-Click 全自動：產出 Notion 並上架 Gumroad", callback_data="btn_full_auto")],
        [InlineKeyboardButton("📢 產出歐美被動獲客文案 / SEO 關鍵字", callback_data="btn_marketing")],
        [InlineKeyboardButton("🔄 重置記憶開啟新專案", callback_data="btn_reset")]
    ]
    return InlineKeyboardMarkup(keyboard)

def is_authorized(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

# 具備 503 重試與雙模型降級備援的安全調用
def ask_gemini_safe(prompt_text: str) -> str:
    global chat_session
    models_to_try = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    
    for attempt in range(3):
        for model_name in models_to_try:
            try:
                response = chat_session.send_message(prompt_text)
                return response.text
            except Exception as e:
                err_str = str(e)
                if "503" in err_str or "UNAVAILABLE" in err_str or "demand" in err_str:
                    time.sleep(2)
                    try:
                        chat_session = ai_client.chats.create(
                            model=model_name,
                            config={"system_instruction": SYSTEM_INSTRUCTION}
                        )
                        response = chat_session.send_message(prompt_text)
                        return response.text
                    except Exception:
                        continue
                else:
                    time.sleep(1)
    res = ai_client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt_text
    )
    return res.text

# 呼叫 Notion 官方 API 自動建立精美結構化子頁面
def create_notion_product_page_sync(title: str, content_markdown: str) -> dict:
    if not NOTION_API_KEY:
        return {"success": False, "error": "尚未設定 NOTION_API_KEY"}

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    # 將生成的 Markdown 轉換為 Notion 區塊
    blocks = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{
                    "type": "text", 
                    "text": {"content": "⚡ High-Performance Workspace & Automation System. Duplicate this to your Notion to start."}
                }],
                "icon": {"emoji": "🚀"}
            }
        }
    ]

    for paragraph in content_markdown.split("\n\n"):
        p = paragraph.strip()
        if not p:
            continue
        if p.startswith("### "):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": p[4:]}}]}
            })
        elif p.startswith("## "):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": p[3:]}}]}
            })
        elif p.startswith("# "):
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": p[2:]}}]}
            })
        elif p.startswith("- [ ] "):
            blocks.append({
                "object": "block",
                "type": "to_do",
                "to_do": {"rich_text": [{"type": "text", "text": {"content": p[6:]}}], "checked": False}
            })
        elif p.startswith("```"):
            code_text = p.strip("`").replace("markdown", "").replace("python", "").strip()
            blocks.append({
                "object": "block",
                "type": "code",
                "code": {"rich_text": [{"type": "text", "text": {"content": code_text[:2000]}}], "language": "plain text"}
            })
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": p[:2000]}}]}
            })

    # 最多放入 95 個 block 防止 API 單次請求限制
    payload = {
        "parent": {"page_id": NOTION_PAGE_ID},
        "properties": {
            "title": {
                "title": [{"type": "text", "text": {"content": title}}]
            }
        },
        "children": blocks[:95]
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        data = res.json()
        if res.status_code == 200:
            notion_url = data.get("url", f"[https://www.notion.so/](https://www.notion.so/){data['id'].replace('-', '')}")
            return {"success": True, "url": notion_url, "id": data["id"]}
        else:
            return {"success": False, "error": data.get("message", "建立 Notion 頁面失敗")}
    except Exception as e:
        return {"success": False, "error": str(e)}

# 呼叫 Gumroad API 自動建立商品並填入交付網址
def create_gumroad_product_sync(name: str, description: str, delivery_url: str, price_cents: int = 999) -> dict:
    if not GUMROAD_ACCESS_TOKEN:
        return {"success": False, "error": "尚未設定 GUMROAD_ACCESS_TOKEN"}
    
    url = "[https://api.gumroad.com/v2/products](https://api.gumroad.com/v2/products)"
    full_desc = f"{description}\n\n---\n🎁 **Instant Access**: Upon purchase, you will receive direct access to your fully editable Notion Workspace:\n{delivery_url}"
    
    payload = {
        "access_token": GUMROAD_ACCESS_TOKEN,
        "name": name,
        "price": price_cents,
        "description": full_desc,
        "custom_permalink": "",
        "require_shipping": "false"
    }
    try:
        res = requests.post(url, data=payload, timeout=25)
        data = res.json()
        if data.get("success"):
            return {
                "success": True,
                "url": data["product"]["short_url"],
                "edit_url": f"[https://app.gumroad.com/products/](https://app.gumroad.com/products/){data['product']['id']}/edit",
                "name": name
            }
        else:
            return {"success": False, "error": data.get("message", "建立商品失敗")}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def run_with_progress_report(status_message, sync_task, initial_text="🧠 Agent 正在執行任務..."):
    await status_message.edit_text(initial_text)
    loop = asyncio.get_running_loop()
    task = loop.run_in_executor(None, sync_task)
    
    elapsed = 0
    while not task.done():
        await asyncio.sleep(40)
        elapsed += 40
        if not task.done():
            try:
                mins = elapsed // 60
                await status_message.edit_text(f"⏳ 正在調度 AI 與多方 API 串接（已用時 {mins} 分鐘，請稍候）...")
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
        "👋 Lucas，全自動數位資產工廠已全線貫通！\n"
        "目前已串聯：【Gemini 大腦】+【Notion 自動建頁排版】+【Gumroad 全自動上架】。\n\n"
        "你可以隨時打字指示方向，或點擊下方按鈕進行全自動操作：",
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
    await update.message.reply_text("🔄 已重置專案記憶！", reply_markup=get_main_menu())

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    user_text = update.message.text
    status_msg = await update.message.reply_text("📥 指令已接收，Agent 正在分析歐美市場並規劃資產內容...")

    prompt = (
        f"這是 Lucas 的最新決策：\n『{user_text}』\n\n"
        "請針對指示進行戰略佈局：\n"
        "1. 評估該題目在歐美遠端與自媒體領域的強烈痛點。\n"
        "2. 規劃最適合直接轉化為 Notion Workspace 的結構大綱。\n"
        "3. 確認定價維持在 $9.99 美元衝量區間。\n"
        "各段落請插入『---DIVIDER---』以便手機分段閱讀。"
    )

    try:
        result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_safe(prompt))
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
        await query.message.reply_text("🔄 已清空記憶！", reply_markup=get_main_menu())
        return

    if data == "btn_idea":
        status_msg = await query.message.reply_text("🔍 Agent 正在篩選歐美高需求且適合 Notion 的藍海選題...")
        prompt = (
            "請為歐美市場推薦 3 個極具吸引力的數位商品選題（定價 $9.99 USD）：\n"
            "重點：專為 Notion 模板或即插即用 AI 提示詞庫設計，能替自由接案者或遠端工作者每週省下 5 小時以上。\n"
            "請用繁體中文向我彙報：英文題目、客群強烈痛點、建議售價、核心模組架構。\n"
            "方案之間請單獨一行輸出『---DIVIDER---』。"
        )
        try:
            result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_safe(prompt))
            await send_formatted_chunks(query.message, result_text, get_main_menu())
        except Exception as e:
            await query.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

    elif data == "btn_full_auto":
        status_msg = await query.message.reply_text("🚀 全自動流程啟動：正在撰寫英文資產 → 建立 Notion 頁面 → 自動上架 Gumroad...")

        def full_autonomous_pipeline():
            # 1. 生成商品資訊與 Markdown 內容
            prompt = (
                "Based on our discussion, generate a complete, high-converting digital product package in STRICT JSON format:\n"
                "{\n"
                '  "title": "Clear English Product Title with Keywords (under 50 chars)",\n'
                '  "sales_copy": "Punchy sales copy (Problem, Solution, What is included) in English (around 200 words)",\n'
                '  "notion_markdown": "Complete, comprehensive, ready-to-use Notion content including Callouts, Checklists (- [ ]), Action Steps, and 3 Plug-and-Play Prompt Chains."\n'
                "}\n"
                "Do NOT wrap in markdown fences."
            )
            raw = ask_gemini_safe(prompt).strip()
            if raw.startswith("```json"):
                raw = raw[7:-3].strip()
            elif raw.startswith("```"):
                raw = raw[3:-3].strip()

            try:
                data_pkg = json.loads(raw)
            except Exception:
                data_pkg = {
                    "title": "Freelance OS: 5-in-1 Notion Workflow & Prompt Engine",
                    "sales_copy": "Save 10+ hours every week. The ultimate Notion operating system for freelancers and solo creators.",
                    "notion_markdown": "# Freelance OS\n\n### ⚡ Quick Start Checklist\n- [ ] Step 1: Duplicate this system\n- [ ] Step 2: Input your clients\n\n### 🤖 High-Conversion Prompt Chain\n```text\nAct as a senior consultant...```"
                }

            # 2. 自動在 Notion 建立頁面
            notion_res = create_notion_product_page_sync(data_pkg["title"], data_pkg["notion_markdown"])
            if not notion_res.get("success"):
                return {"success": False, "error": f"Notion 頁面建立失敗: {notion_res.get('error')}"}

            delivery_url = notion_res["url"]

            # 3. 自動在 Gumroad 建立商品並塞入該 Notion 網址
            gumroad_res = create_gumroad_product_sync(
                name=data_pkg["title"],
                description=data_pkg["sales_copy"],
                delivery_url=delivery_url,
                price_cents=999
            )

            if not gumroad_res.get("success"):
                return {"success": False, "error": f"Gumroad 上架失敗: {gumroad_res.get('error')}"}

            return {
                "success": True,
                "title": data_pkg["title"],
                "notion_url": delivery_url,
                "gumroad_url": gumroad_res["url"],
                "edit_url": gumroad_res["edit_url"]
            }

        try:
            res = await run_with_progress_report(status_msg, full_autonomous_pipeline, "⚡ 正在打通 Notion 與 Gumroad 全流程，請稍候...")
            if res.get("success"):
                reply = (
                    f"🎉 **數位資產已 100% 全自動發布完畢！**\n\n"
                    f"🏷 **商品名稱**：\n{res['title']}\n\n"
                    f"💲 **設定售價**：$9.99 美元\n\n"
                    f"📝 **已自動生成之 Notion 交付頁面**：\n{res['notion_url']}\n\n"
                    f"🛒 **全球直接購買網址（發給買家/貼文引流）**：\n{res['gumroad_url']}\n\n"
                    f"⚙️ **Gumroad 後台管理**：\n{res['edit_url']}\n\n"
                    f"💡 *買家購買後，系統將自動導向你的 Notion 頁面供其一鍵 Duplicate！完全無須手動介入。*"
                )
            else:
                reply = f"❌ 自動化中斷：{res.get('error')}"
            await query.message.reply_text(reply, reply_markup=get_main_menu())
        except Exception as e:
            await query.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

    elif data == "btn_marketing":
        status_msg = await query.message.reply_text("✍️ 正在為該商品產出 Google SEO 搜尋詞與海外價值貼文...")
        prompt = (
            "請為我們目前上架的 Gumroad 數位商品產出以下兩項素材：\n"
            "1. 【Google 程式化 SEO 標籤】：5 組歐美用戶搜尋量高、精準命中痛點的長尾英文關鍵字。\n"
            "2. 【價值錨定貼文（純英文）】：1 篇用於 Reddit / X 的無痛點分享推文（先送出 20% 乾貨提示詞，文末自然引導至 Gumroad 完整版）。\n"
            "兩者之間請單獨一行輸出『---DIVIDER---』。"
        )
        try:
            result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_safe(prompt))
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
    print("全自動數位資產工廠運作中...")
    app.run_polling()

if __name__ == "__main__":
    main()
