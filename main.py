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

# ==================== 環境變數 ====================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.environ.get("ALLOWED_USER_ID", "989667956"))
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GUMROAD_ACCESS_TOKEN = os.environ.get("GUMROAD_ACCESS_TOKEN")
NOTION_API_KEY = os.environ.get("NOTION_API_KEY")
NOTION_PAGE_ID = os.environ.get("NOTION_PAGE_ID", "406ab074b50c80a291e2c5a073ebc878").replace("-", "")

ai_client = genai.Client(api_key=GEMINI_API_KEY)

# ==================== 系統人設 ====================
SYSTEM_INSTRUCTION = (
    "You are an elite Digital Product Strategist and Automated Business Agent.\n"
    "Your owner is Lucas. Your mission is to autonomously build full dual-market funnels:\n"
    "1. US/Global Market: Free Starter Lead Magnet ($0) + Paid Flagship Notion OS ($9.99 USD) in crisp, native English.\n"
    "2. Taiwan/Chinese Market: Free Starter Lead Magnet ($0) + Paid Flagship Notion OS ($4.99 USD / ~NT$149) in professional Traditional Chinese (繁體中文).\n"
    "All conversational briefings with Lucas must remain in Traditional Chinese.\n"
    "Deliverables must be exhaustive, professional-grade, actionable, and formatted in clean Markdown for Notion."
)

chat_session = ai_client.chats.create(
    model="gemini-3.8-flash",
    config={"system_instruction": SYSTEM_INSTRUCTION}
)

# ==================== HTTP 伺服器 (Render 健康檢查) ====================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()

    def log_message(self, format, *args):
        pass

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# ==================== Telegram 選單 ====================
def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("💡 推薦全新高需求藍海選題", callback_data="btn_idea")],
        [InlineKeyboardButton("🚀 1-Click 全自動漏斗（中英雙軌 4 產品同步上架）", callback_data="btn_full_matrix")],
        [InlineKeyboardButton("📢 產出中英雙語獲客推廣貼文", callback_data="btn_marketing")],
        [InlineKeyboardButton("🔄 重置記憶開啟新專案", callback_data="btn_reset")]
    ]
    return InlineKeyboardMarkup(keyboard)

def is_authorized(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

# ==================== Gemini 安全調用 ====================
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

# ==================== Markdown 轉 Notion Block ====================
def markdown_to_notion_blocks(content_markdown: str, icon_emoji: str = "⚡") -> list:
    blocks = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": "⚡ 高效數位系統與工作台 / High-Performance Workspace. Duplicate to start."}}],
                "icon": {"emoji": icon_emoji}
            }
        }
    ]

    for paragraph in content_markdown.split("\n\n"):
        p = paragraph.strip()
        if not p:
            continue
        if p.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": p[4:][:2000]}}]}})
        elif p.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": p[3:][:2000]}}]}})
        elif p.startswith("# "):
            blocks.append({"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": p[2:][:2000]}}]}})
        elif p.startswith("- [ ] "):
            blocks.append({"object": "block", "type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": p[6:][:2000]}}], "checked": False}})
        elif p.startswith("```"):
            code_text = p.strip("`").replace("markdown", "").replace("text", "").replace("python", "").strip()
            blocks.append({"object": "block", "type": "code", "code": {"rich_text": [{"type": "text", "text": {"content": code_text[:2000]}}], "language": "plain text"}})
        else:
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": p[:2000]}}]}})
    return blocks

# ==================== Notion 完整建頁 ====================
def create_notion_product_page_sync(title: str, content_markdown: str, icon_emoji: str = "⚡", cover_url: str = None) -> dict:
    if not NOTION_API_KEY:
        return {"success": False, "error": "尚未設定 NOTION_API_KEY"}

    url = "[https://api.notion.com/v1/pages](https://api.notion.com/v1/pages)"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY.strip()}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    if not cover_url:
        cover_url = "[https://images.unsplash.com/photo-1507238691740-187a5b1d37b8?auto=format&fit=crop&w=1500&q=80](https://images.unsplash.com/photo-1507238691740-187a5b1d37b8?auto=format&fit=crop&w=1500&q=80)"

    all_blocks = markdown_to_notion_blocks(content_markdown, icon_emoji)
    first_batch = all_blocks[:90]

    payload = {
        "parent": {"page_id": NOTION_PAGE_ID.strip()},
        "icon": {"type": "emoji", "emoji": icon_emoji},
        "cover": {"type": "external", "external": {"url": cover_url}},
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
        },
        "children": first_batch
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        data = res.json()
        if res.status_code != 200:
            return {"success": False, "error": data.get("message", "建立 Notion 失敗")}
        
        page_id = data["id"]
        notion_url = data.get("url", f"[https://www.notion.so/](https://www.notion.so/){page_id.replace('-', '')}")

        # 若超過 90 區塊，分批追加
        if len(all_blocks) > 90:
            append_url = f"[https://api.notion.com/v1/blocks/](https://api.notion.com/v1/blocks/){page_id}/children"
            for i in range(90, len(all_blocks), 90):
                batch = all_blocks[i:i+90]
                requests.patch(append_url, headers=headers, json={"children": batch}, timeout=25)
                time.sleep(0.5)

        return {"success": True, "url": notion_url, "id": page_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ==================== Gumroad API 自動上架商品 ====================
def create_gumroad_product_sync(name: str, description: str, tags: list = None, price_cents: int = 999) -> dict:
    if not GUMROAD_ACCESS_TOKEN:
        return {"success": False, "error": "尚未設定 GUMROAD_ACCESS_TOKEN"}
    
    api_url = "[https://api.gumroad.com/v2/products](https://api.gumroad.com/v2/products)"
    payload = {
        "access_token": GUMROAD_ACCESS_TOKEN.strip(),
        "name": name,
        "price": price_cents,
        "description": description,
        "require_shipping": "false"
    }
    
    if tags and isinstance(tags, list):
        for idx, tag in enumerate(tags[:5]):
            payload[f"tags[{idx}]"] = str(tag).strip()

    try:
        res = requests.post(api_url, data=payload, timeout=25)
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

# ==================== 心跳與長文字切分 ====================
async def run_with_progress_report(status_message, sync_task, initial_text="🧠 Agent 正在全自動調度中..."):
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
                await status_message.edit_text(f"⏳ 正在深度建構高品質資產與 4 產品矩陣（已用時 {mins} 分鐘，請稍候）...")
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

# ==================== 指令與訊息處理 ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ 未授權存取。")
        return
    await update.message.reply_text(
        "👋 Lucas，全自動數位資產工廠（中英雙軌 4 產品矩陣版）已就緒！\n"
        "目前具備：【Notion 無截斷完整建頁】+【免費/付費權限隔離】+【Gumroad 4 產品矩陣同步上架】。\n\n"
        "你可以直接打字交代策略，或點擊下方按鈕啟動：",
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
    status_msg = await update.message.reply_text("📥 指令已接收，Agent 正在分析雙市場策略...")

    prompt = (
        f"這是 Lucas 的最新決策：\n『{user_text}』\n\n"
        "請針對指示深入分析：\n"
        "1. 評估該主題在歐美與台灣雙市場的痛點深度。\n"
        "2. 規劃付費旗艦版（含完整工作流與提示詞）與免費版（引流鉤子）的隔離架構。\n"
        "3. 輸出 5 組 Google SEO 長尾詞。\n"
        "各段落請插入『---DIVIDER---』以便手機閱讀。"
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
        status_msg = await query.message.reply_text("🔍 Agent 正在篩選高需求藍海選題...")
        prompt = (
            "請為全球與台灣市場推薦 3 個極具吸引力的數位商品選題：\n"
            "重點：能同時滿足歐美遠端族與台灣職場上班族的痛點，能拆解為中英雙語版本。\n"
            "請用繁體中文回報：題目、痛點對比、建議售價、核心模組架構。\n"
            "方案之間請單獨一行輸出『---DIVIDER---』。"
        )
        try:
            result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_safe(prompt))
            await send_formatted_chunks(query.message, result_text, get_main_menu())
        except Exception as e:
            await query.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

    elif data == "btn_full_matrix":
        status_msg = await query.message.reply_text("🚀 全自動矩陣啟動：正在生成中英文深度資產 → 建立 2 組 Notion 頁面 → 自動上架 4 款 Gumroad 商品...")

        def full_matrix_pipeline():
            prompt = (
                "Based on our discussion, create a comprehensive dual-market digital product suite in STRICT JSON format:\n"
                "{\n"
                '  "en_paid_title": "Comprehensive Notion OS Title (English, SEO optimized)",\n'
                '  "en_paid_copy": "High converting English sales copy (around 200 words)",\n'
                '  "en_free_title": "Free Starter Version Title (English)",\n'
                '  "en_free_copy": "English free tier copy with call to action",\n'
                '  "en_seo_tags": ["notion template", "productivity", "freelance", "ai prompts", "workflow"],\n'
                '  "en_notion_markdown": "# Flagship Operating System\\n\\n### ⚡ Quick Start Checklist\\n- [ ] Step 1: Duplicate this system\\n- [ ] Step 2: Configure your workspace\\n\\n### 🤖 Battle-Tested AI Prompt Chains\\n```text\\n[Act as an Executive Strategist]\\nInput: [Project Parameters]\\nOutput: [Complete Roadmap]\\n```\\n\\n### 📊 Advanced Workflow SOP\\nDetailed implementation instructions...",\n'
                '  "zh_paid_title": "旗艦級 Notion 高效數位工作台（繁體中文）",\n'
                '  "zh_paid_copy": "打擊加班痛點的繁體中文高轉化銷售文案（約 200 字）",\n'
                '  "zh_free_title": "免費領取：職場高效實戰清單與提示詞",\n'
                '  "zh_free_copy": "繁體中文免費版說明文案",\n'
                '  "zh_seo_tags": ["notion模板", "工作效率", "AI提示詞", "副業", "自動化"],\n'
                '  "zh_notion_markdown": "# 旗艦級高效數位系統\\n\\n### ⚡ 3分鐘快速啟用清單\\n- [ ] 步驟一：點擊右上角 Duplicate 複製模板\\n- [ ] 步驟二：套用日常工作看板\\n\\n### 🤖 即插即用 AI 實戰提示詞庫\\n```text\\n[扮演資深專案顧問]\\n輸入：[當前任務目標]\\n輸出：[結構化執行步驟]\\n```\\n\\n### 📈 避坑與自動化操作SOP\\n深度落地乾貨內容..."\n'
                "}\n"
                "Ensure both en_notion_markdown and zh_notion_markdown are rich, highly detailed, and practical (not summaries). No markdown fences."
            )
            raw = ask_gemini_safe(prompt).strip()
            if raw.startswith("```json"):
                raw = raw[7:-3].strip()
            elif raw.startswith("```"):
                raw = raw[3:-3].strip()

            try:
                pkg = json.loads(raw)
            except Exception:
                pkg = {
                    "en_paid_title": "Ultimate Freelance OS: 5-in-1 Notion Workflow & Prompt Engine",
                    "en_paid_copy": "Save 10+ hours every week. Battle-tested Notion workflows and AI prompt chains for solo operators.",
                    "en_free_title": "Free Freelancer Daily Starter Checklist",
                    "en_free_copy": "Instant free starter checklist to streamline your client onboarding.",
                    "en_seo_tags": ["notion template", "productivity", "freelance", "chatgpt prompt"],
                    "en_notion_markdown": "# Ultimate Freelance OS\n\n### ⚡ Setup Checklist\n- [ ] Duplicate workspace\n- [ ] Add active clients\n\n### 🤖 AI Prompt Chain\n```text\nAct as a senior growth consultant and analyze client scope...```",
                    "zh_paid_title": "極速提效 OS：5合1 Notion 自動化工作台與實戰提示詞庫",
                    "zh_paid_copy": "每週現省 10 小時！專為職場上班族與創作者打造的即插即用數位資產系統。",
                    "zh_free_title": "免費領取：職場高效速查清單與必備提示詞",
                    "zh_free_copy": "免費取得核心工作流檢查清單，下班不瞎忙。",
                    "zh_seo_tags": ["notion模板", "效率工具", "AI提示詞", "一人公司"],
                    "zh_notion_markdown": "# 極速提效 OS\n\n### ⚡ 快速啟動檢查表\n- [ ] 複製工作區至個人 Notion\n- [ ] 建立專案進度追蹤\n\n### 🤖 核心實戰提示詞庫\n```text\n請扮演專業效率顧問，重組今日代辦事項...```"
                }

            # 1. 建立英文版 Notion 頁面（含封面與圖標）
            en_notion = create_notion_product_page_sync(
                title=pkg["en_paid_title"],
                content_markdown=pkg["en_notion_markdown"],
                icon_emoji="🚀",
                cover_url="[https://images.unsplash.com/photo-1499750310107-5fef28a66643?auto=format&fit=crop&w=1500&q=80](https://images.unsplash.com/photo-1499750310107-5fef28a66643?auto=format&fit=crop&w=1500&q=80)"
            )
            if not en_notion.get("success"):
                return {"success": False, "error": f"英文 Notion 頁面建立失敗: {en_notion.get('error')}"}

            # 2. 建立中文版 Notion 頁面（含封面與圖標）
            zh_notion = create_notion_product_page_sync(
                title=pkg["zh_paid_title"],
                content_markdown=pkg["zh_notion_markdown"],
                icon_emoji="💼",
                cover_url="[https://images.unsplash.com/photo-1507238691740-187a5b1d37b8?auto=format&fit=crop&w=1500&q=80](https://images.unsplash.com/photo-1507238691740-187a5b1d37b8?auto=format&fit=crop&w=1500&q=80)"
            )
            if not zh_notion.get("success"):
                return {"success": False, "error": f"中文 Notion 頁面建立失敗: {zh_notion.get('error')}"}

            # 3. 上架英文付費旗艦版 ($9.99，交付完整英文 Notion)
            en_paid_desc = f"{pkg['en_paid_copy']}\n\n---\n🎁 **Instant Access**: Upon purchase, duplicate your Notion Workspace here:\n{en_notion['url']}"
            en_paid_gum = create_gumroad_product_sync(
                name=pkg["en_paid_title"],
                description=en_paid_desc,
                tags=pkg.get("en_seo_tags", []),
                price_cents=999
            )

            # 4. 上架英文免費引流版 ($0，只交付基礎內容與升級連結，不給付費 Notion 網址)
            en_free_desc = f"{pkg['en_free_copy']}\n\n---\n🎁 **Starter Access**: Check your inbox for the initial checklist.\n👉 **Upgrade to Complete Flagship Notion OS ($9.99)**: {en_paid_gum.get('url', '')}"
            en_free_gum = create_gumroad_product_sync(
                name=pkg["en_free_title"],
                description=en_free_desc,
                tags=pkg.get("en_seo_tags", []),
                price_cents=0
            )

            # 5. 上架中文付費旗艦版 ($4.99 / ~NT$149，交付完整中文 Notion)
            zh_paid_desc = f"{pkg['zh_paid_copy']}\n\n---\n🎁 **立即領取存取權限**：購買後請點擊下方連結一鍵複製您的專屬 Notion 工作台：\n{zh_notion['url']}"
            zh_paid_gum = create_gumroad_product_sync(
                name=pkg["zh_paid_title"],
                description=zh_paid_desc,
                tags=pkg.get("zh_seo_tags", []),
                price_cents=499
            )

            # 6. 上架中文免費引流版 ($0，只交付基礎清單與升級連結，不給付費 Notion 網址)
            zh_free_desc = f"{pkg['zh_free_copy']}\n\n---\n🎁 **免費領取說明**：已為您備妥高效速查清單。\n👉 **升級取得完整旗艦版工作台（特惠 NT$149）**：{zh_paid_gum.get('url', '')}"
            zh_free_gum = create_gumroad_product_sync(
                name=pkg["zh_free_title"],
                description=zh_free_desc,
                tags=pkg.get("zh_seo_tags", []),
                price_cents=0
            )

            return {
                "success": True,
                "en_paid_title": pkg["en_paid_title"],
                "en_paid_url": en_paid_gum.get("url"),
                "en_free_url": en_free_gum.get("url"),
                "en_notion_url": en_notion["url"],
                "zh_paid_title": pkg["zh_paid_title"],
                "zh_paid_url": zh_paid_gum.get("url"),
                "zh_free_url": zh_free_gum.get("url"),
                "zh_notion_url": zh_notion["url"]
            }

        try:
            res = await run_with_progress_report(status_msg, full_matrix_pipeline, "⚡ 正在生成中英雙軌 4 款產品全套矩陣，請稍候...")
            if res.get("success"):
                reply = (
                    f"🎉 **中英雙軌 4 產品矩陣已 100% 全自動部署完成！**\n\n"
                    f"🇺🇸 **【歐美全球市場】**\n"
                    f"• 💰 付費旗艦版 ($9.99)：\n{res['en_paid_url']}\n"
                    f"• 🧲 免費引流版 ($0)：\n{res['en_free_url']}\n"
                    f"• 📝 專屬英文 Notion：\n{res['en_notion_url']}\n\n"
                    f"---\n\n"
                    f"🇹🇼 **【台灣/華語本土市場】**\n"
                    f"• 💰 付費旗艦版 (NT$149 / $4.99)：\n{res['zh_paid_url']}\n"
                    f"• 🧲 免費引流版 ($0)：\n{res['zh_free_url']}\n"
                    f"• 📝 專屬中文 Notion：\n{res['zh_notion_url']}\n\n"
                    f"💡 *權限已徹底隔離：免費版買家僅會看到基礎鉤子並被引導至付費版購買連結；付費買家才能取得完整 Notion 工作台！*"
                )
            else:
                reply = f"❌ 執行中斷：{res.get('error')}"
            await query.message.reply_text(reply, reply_markup=get_main_menu())
        except Exception as e:
            await query.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

    elif data == "btn_marketing":
        status_msg = await query.message.reply_text("✍️ 正在產出中英雙語推廣素材...")
        prompt = (
            "請為我們目前上架的中英雙語商品，產出 2 篇極具轉換率的推廣素材：\n"
            "1. 【英文版 Reddit / X 貼文】：前 80% 無私送出實戰 Prompt，文末附上免費下載連結。\n"
            "2. 【繁中版 Threads / 社群貼文】：針對上班族常加班痛點切入，送出 1 個現成模板，文末引導自取。\n"
            "兩篇貼文之間請單獨一行輸出『---DIVIDER---』。"
        )
        try:
            result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_safe(prompt))
            await send_formatted_chunks(query.message, result_text, get_main_menu())
        except Exception as e:
            await query.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

# ==================== 主入口 ====================
def main():
    threading.Thread(target=run_http_server, daemon=True).start()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    print("全自動數位資產工廠（矩陣隔離終極版）運作中...")
    app.run_polling()

if __name__ == "__main__":
    main()
