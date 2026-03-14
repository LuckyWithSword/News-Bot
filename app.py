import os
import requests
import schedule
import threading
import time
from datetime import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
gemini = genai.GenerativeModel("gemini-1.5-flash")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
YOUR_TELEGRAM_CHAT_ID = os.environ.get("YOUR_TELEGRAM_CHAT_ID")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY")

NEWS_TOPICS = ["world news", "technology", "AI"]

conversation_histories = {}

def fetch_news(topic, count=5):
    url = "https://newsapi.org/v2/everything"
    params = {"q": topic, "sortBy": "publishedAt", "pageSize": count, "language": "en", "apiKey": NEWS_API_KEY}
    res = requests.get(url, params=params, timeout=10)
    res.raise_for_status()
    articles = res.json().get("articles", [])
    return [{"title": a["title"], "description": a.get("description", "")}
            for a in articles if a.get("title") and "[Removed]" not in a["title"]]

def build_news_context():
    sections = []
    for topic in NEWS_TOPICS:
        try:
            articles = fetch_news(topic)
            if articles:
                block = f"\n### {topic.upper()}\n"
                for i, a in enumerate(articles, 1):
                    block += f"{i}. {a['title']}\n   {a['description']}\n"
                sections.append(block)
        except Exception as e:
            sections.append(f"\n### {topic.upper()}\nCould not fetch: {e}\n")
    return "\n".join(sections)

def generate_daily_digest(news_context):
    prompt = (
        "You are a friendly daily news assistant. Summarize these headlines into a short "
        "Telegram morning digest. Plain text only, no markdown. Group by topic. "
        "End with one short motivational line.\n\nHeadlines:\n" + news_context
    )
    return gemini.generate_content(prompt).text

def answer_question(user_id, question, news_context):
    history = conversation_histories.get(user_id, [])
    history_text = "\n".join([f"{'User' if m['role']=='user' else 'Bot'}: {m['content']}" for m in history])
    prompt = (
        "You are a helpful news assistant on Telegram. Short and conversational. Plain text only.\n\n"
        f"Today's news:\n{news_context}\n\nConversation:\n{history_text}\n\nUser: {question}\nBot:"
    )
    reply = gemini.generate_content(prompt).text.strip()
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": reply})
    conversation_histories[user_id] = history[-10:]
    return reply

_news = {"context": ""}

def get_news():
    if not _news["context"]:
        _news["context"] = build_news_context()
    return _news["context"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Hey! Your News Bot is live!\nYour Chat ID: {update.effective_chat.id}\n\n"
        "Commands:\n/news - Get latest digest\n/topics - See current topics\n\n"
        "Or just ask me anything about the news!"
    )

async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Fetching your news... one sec!")
    digest = generate_daily_digest(get_news())
    await update.message.reply_text(f"Your News Digest:\n\n{digest}")

async def topics_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Current topics: {', '.join(NEWS_TOPICS)}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = answer_question(str(update.effective_user.id), update.message.text, get_news())
    await update.message.reply_text(reply)

def send_daily_digest(app):
    _news["context"] = build_news_context()
    digest = generate_daily_digest(_news["context"])
    import asyncio
    asyncio.run(app.bot.send_message(chat_id=YOUR_TELEGRAM_CHAT_ID, text=f"Good morning! Here is your daily news digest:\n\n{digest}"))

def run_scheduler(app):
    schedule.every().day.at("08:00").do(send_daily_digest, app)
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("news", news_command))
    app.add_handler(CommandHandler("topics", topics_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    threading.Thread(target=run_scheduler, args=(app,), daemon=True).start()
    print("Bot is running...")
    app.run_polling()
