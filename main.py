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

# 歐美市場專屬高階人設
SYSTEM_INSTRUCTION = (
    "You are an elite Digital Product Strategist and Automated Business Agent targeting the US/Global market.\n"
    "Your owner is Lucas. Your mission is to autonomously build full sales funnels: free lead magnets ($0), "
    "paid flagship Notion templates ($9.99), curated cover art, icons, SEO tags, and automated email sequences.\n"
    "Guidelines:\n"
    "1. All product deliverables, descriptions, emails, and SEO tags must be in professional, crisp English.\n"
    "2. All conversational status reports with Lucas must remain in Traditional Chinese (繁體中文).\n"
    "3. Focus on solving real productivity bottlenecks for remote workers, freelancers, and solo creators.\n"
    "4. When outputting sections, separate them with '---DIVIDER---'."
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
        [InlineKeyboardButton("🚀 1-Click 全自動漏斗（Notion視覺化+Gumroad雙版本）", callback_data="btn_full_funnel")],
        [InlineKeyboardButton("📢 產出歐美被動獲客貼文 / 導流文案", callback_data="btn_marketing")],
        [InlineKeyboardButton("🔄 重置記憶開啟新專案", callback_data="btn_reset")]
    ]
    return InlineKeyboardMarkup(keyboard)

def is_authorized(user_id: int) -> bool:
    return user_id == ALLOWED_USER_ID

# 具備 503 重試與雙模型降級備援
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

# 呼叫 Notion 官方 API：自動配置 Cover 橫幅圖、Icon 圖標與精美排版
def create_notion_product_page_sync(title: str, content_markdown: str, icon_emoji: str = "⚡", cover_url: str = None) -> dict:
    if not NOTION_API_KEY:
        return {"success": False, "error": "尚未設定 NOTION_API_KEY"}

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    # 預設極簡商務/科技高解析度橫幅
    if not cover_url:
        cover_url = "https://images.unsplash.com/photo-1507238691740-187a5b1d37b8?auto=format&fit=crop&w=1500&q=80"

    blocks = [
        {
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"type": "text", "text": {"content": "⚡ High-Performance Workspace. Duplicate to your Notion to start."}}],
                "icon": {"emoji": icon_emoji}
            }
        }
    ]

    for paragraph in content_markdown.split("\n\n"):
        p = paragraph.strip()
        if not p:
            continue
        if p.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"type": "text", "text": {"content": p[4:]}}]}})
        elif p.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"type": "text", "text": {"content": p[3:]}}]}})
        elif p.startswith("# "):
            blocks.append({"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"type": "text", "text": {"content": p[2:]}}]}})
        elif p.startswith("- [ ] "):
            blocks.append({"object": "block", "type": "to_do", "to_do": {"rich_text": [{"type": "text", "text": {"content": p[6:]}}], "checked": False}})
        elif p.startswith("```"):
            code_text = p.strip("`").replace("markdown", "").replace("text", "").strip()
            blocks.append({"object": "block", "type": "code", "code": {"rich_text": [{"type": "text", "text": {"content": code_text[:2000]}}], "language": "plain text"}})
        else:
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": [{"type": "text", "text": {"content": p[:2000]}}]}})

    payload = {
        "parent": {"page_id": NOTION_PAGE_ID},
        "icon": {
            "type": "emoji",
            "emoji": icon_emoji
        },
        "cover": {
            "type": "external",
            "external": {
                "url": cover_url
            }
        },
        "properties": {
            "title": {"title": [{"type": "text", "text": {"content": title}}]}
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
            return {"success": False, "error": data.get("message", "建立 Notion 失敗")}
    except Exception as e:
        return {"success": False, "error": str(e)}

# 呼叫 Gumroad API 自動建立商品
def create_gumroad_product_sync(name: str, description: str, delivery_url: str, tags: list = None, price_cents: int = 999) -> dict:
    if not GUMROAD_ACCESS_TOKEN:
        return {"success": False, "error": "尚未設定 GUMROAD_ACCESS_TOKEN"}
    
    url = "[https://api.gumroad.com/v2/products](https://api.gumroad.com/v2/products)"
    full_desc = f"{description}\n\n---\n🎁 **Instant Access**: Upon purchase, duplicate your Notion Workspace here:\n{delivery_url}"
    
    payload = {
        "access_token": GUMROAD_ACCESS_TOKEN,
        "name": name,
        "price": price_cents,
        "description": full_desc,
        "require_shipping": "false"
    }
    if tags:
        payload["tags[]"] = tags

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
                await status_message.edit_text(f"⏳ 正在全自動配置 Notion 視覺化封面、排版與雙版本上架中（已用時 {mins} 分鐘）...")
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
        "👋 Lucas，全自動數位資產工廠（旗艦視覺化版）已就緒！\n"
        "目前具備：【Notion Cover/Icon 自動生成】+【Gumroad 免費+付費雙版本自動上架】+【SEO Tags 自動注入】+【追銷信生成】。\n\n"
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
    status_msg = await update.message.reply_text("📥 指令已接收，Agent 正在分析並組織全球策略...")

    prompt = (
        f"這是 Lucas 的最新決策：\n『{user_text}』\n\n"
        "請針對指示深入分析：\n"
        "1. 評估該主題在歐美受眾中的痛點強度。\n"
        "2. 規劃一套『$0 免費引流版 + $9.99 旗艦版』的雙層商品架構。\n"
        "3. 輸出 5 組精準的 Google SEO 長尾搜尋詞與適合的 Notion Icon/Cover 風格建議。\n"
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
        status_msg = await query.message.reply_text("🔍 Agent 正在篩選歐美高需求選題...")
        prompt = (
            "請為歐美市場推薦 3 個極具吸引力的數位商品選題：\n"
            "重點：能同時拆解為『$0 免費鉤子』與『$9.99 完整版』的 Notion 模板與提示詞庫。\n"
            "請用繁體中文回報：題目、痛點、5組SEO標籤、模組架構。\n"
            "方案之間請單獨一行輸出『---DIVIDER---』。"
        )
        try:
            result_text = await run_with_progress_report(status_msg, lambda: ask_gemini_safe(prompt))
            await send_formatted_chunks(query.message, result_text, get_main_menu())
        except Exception as e:
            await query.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

    elif data == "btn_full_funnel":
        status_msg = await query.message.reply_text("🚀 全自動流程啟動：正在生成封面/圖標、建立 Notion 頁面、注入 SEO Tags 與雙版本上架...")

        def full_funnel_pipeline():
            prompt = (
                "Based on our discussion, output STRICTLY a JSON object without markdown fences:\n"
                "{\n"
                '  "paid_title": "Flagship Notion OS Title (with SEO keywords)",\n'
                '  "paid_sales_copy": "High converting sales copy in English (around 200 words)",\n'
                '  "free_title": "Free Starter Version Title (e.g. Free Notion Daily Checklist)",\n'
                '  "free_sales_copy": "Short sales copy in English for the free tier",\n'
                '  "icon_emoji": "⚡",\n'
                '  "cover_image_url": "[https://images.unsplash.com/photo-1499750310107-5fef28a66643?auto=format&fit=crop&w=1500&q=80](https://images.unsplash.com/photo-1499750310107-5fef28a66643?auto=format&fit=crop&w=1500&q=80)",\n'
                '  "seo_tags": ["notion template", "productivity", "freelance", "chatgpt prompts", "workflow"],\n'
                '  "follow_up_email_subject": "Quick question about your Notion setup...",\n'
                '  "follow_up_email_body": "Persuasive email copy pitching the paid upgrade to users who downloaded the free version",\n'
                '  "notion_markdown": "# Flagship Notion System\\n\\n### ⚡ Quick Start\\n- [ ] Duplicate system\\n\\n### 🤖 Core Prompt Chains\\n```text\\nAct as an expert...```"\n'
                "}"
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
                    "paid_title": "Freelance OS: 5-in-1 Notion Workflow & Prompt Engine",
                    "paid_sales_copy": "The ultimate Notion operating system for solo creators. Save 10+ hours every week.",
                    "free_title": "Free Freelancer Starter Checklist & Prompt",
                    "free_sales_copy": "Instant free starter checklist to streamline your client onboarding.",
                    "icon_emoji": "💼",
                    "cover_image_url": "[https://images.unsplash.com/photo-1507238691740-187a5b1d37b8?auto=format&fit=crop&w=1500&q=80](https://images.unsplash.com/photo-1507238691740-187a5b1d37b8?auto=format&fit=crop&w=1500&q=80)",
                    "seo_tags": ["notion template", "freelancer os", "productivity", "chatgpt prompt"],
                    "follow_up_email_subject": "How to scale your freelance business with Notion...",
                    "follow_up_email_body": "Hey there! Thanks for downloading the free checklist. If you are ready for the complete automated system, check out Freelance OS below.",
                    "notion_markdown": "# Freelance OS\\n\\n### ⚡ Client Onboarding\\n- [ ] Send invoice\\n- [ ] Duplicate workspace"
                }

            # 1. 自動建 Notion 頁面（含封面與圖標）
            notion_res = create_notion_product_page_sync(
                title=pkg["paid_title"],
                content_markdown=pkg["notion_markdown"],
                icon_emoji=pkg.get("icon_emoji", "⚡"),
                cover_url=pkg.get("cover_image_url")
            )
            if not notion_res.get("success"):
                return {"success": False, "error": f"Notion 頁面建立失敗: {notion_res.get('error')}"}
            delivery_url = notion_res["url"]

            # 2. 自動建 $9.99 付費旗艦版（自動注入 Tags）
            paid_gum = create_gumroad_product_sync(
                name=pkg["paid_title"],
                description=pkg["paid_sales_copy"],
                delivery_url=delivery_url,
                tags=pkg.get("seo_tags", []),
                price_cents=999
            )
            if not paid_gum.get("success"):
                return {"success": False, "error": f"付費版上架失敗: {paid_gum.get('error')}"}

            # 3. 自動建 $0 免費引流版（自動注入 Tags 並帶入付費版連結）
            free_desc = f"{pkg['free_sales_copy']}\n\n👉 Upgrade to Full Version: {paid_gum['url']}"
            free_gum = create_gumroad_product_sync(
                name=pkg["free_title"],
                description=free_desc,
                delivery_url=delivery_url,
                tags=pkg.get("seo_tags", []),
                price_cents=0
            )

            return {
                "success": True,
                "paid_title": pkg["paid_title"],
                "paid_url": paid_gum["url"],
                "free_title": pkg["free_title"],
                "free_url": free_gum.get("url", "建立中"),
                "notion_url": delivery_url,
                "email_subject": pkg.get("follow_up_email_subject"),
                "email_body": pkg.get("follow_up_email_body"),
                "tags": ", ".join(pkg.get("seo_tags", []))
            }

        try:
            res = await run_with_progress_report(status_msg, full_funnel_pipeline, "⚡ 正在配置 Notion 視覺化封面、雙版本上架與 SEO 全流程...")
            if res.get("success"):
                reply = (
                    f"🎉 **全自動視覺化數位資產已全線部署完畢！**\n\n"
                    f"🏷 **自動注入 SEO 標籤**：\n`{res['tags']}`\n\n"
                    f"🧲 **【$0 免費引流版】（被動收集 Email）**：\n{res['free_url']}\n\n"
                    f"💰 **【$9.99 付費旗艦版】（自動變現）**：\n{res['paid_url']}\n\n"
                    f"📝 **Notion 交付頁面（已自動配置 Icon 與高清 Cover）**：\n{res['notion_url']}\n\n"
                    f"---\n"
                    f"✉️ **自動追銷信模板**：\n"
                    f"**主旨**：{res['email_subject']}\n"
                    f"**內文**：\n{res['email_body']}\n\n"
                    f"💡 *買家點開 Notion 頁面時，將看到完整橫幅與大頭貼排版，極具專業質感！*"
                )
            else:
                reply = f"❌ 執行中斷：{res.get('error')}"
            await query.message.reply_text(reply, reply_markup=get_main_menu())
        except Exception as e:
            await query.message.reply_text(f"⚠️ 異常：{str(e)}", reply_markup=get_main_menu())

    elif data == "btn_marketing":
        status_msg = await query.message.reply_text("✍️ 正在產出海外被動獲客貼文...")
        prompt = (
            "請為我們目前建立的免費版與付費版 Gumroad 數位商品，撰寫 1 篇發布於 Reddit / X 的純英文無痛點分享推文：\n"
            "重點：前 80% 無私送出實用提示詞與工作清單，文末自然放上免費下載連結。\n"
            "不用任何推銷字眼，完全以同儕分享口吻呈現。"
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
    print("全自動數位資產工廠（旗艦版）運作中...")
    app.run_polling()

if __name__ == "__main__":
    main()
