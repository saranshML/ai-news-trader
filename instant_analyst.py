import os
import argparse
import feedparser
import requests
import google.generativeai as genai
import urllib.parse
from datetime import datetime, timedelta

# --- CONFIGURATION ---
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']

genai.configure(api_key=GEMINI_API_KEY)

def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id, 
        "text": message, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    requests.post(url, json=payload)

def get_ai_verdict(stock, news_list):
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        # We combine headlines to give AI more context
        combined_news = "\n".join([f"- {n['title']}" for n in news_list])
        
        prompt = (
            f"STOCK: {stock}\n"
            f"RECENT NEWS:\n{combined_news}\n\n"
            "ROLE: Senior Financial Analyst.\n"
            "TASK: Analyze these headlines for immediate market impact.\n"
            "OUTPUT FORMAT:\n"
            "Verdict: [BULLISH/BEARISH/NEUTRAL]\n"
            "Confidence: [High/Med/Low]\n"
            "Summary: [One sentence explaining why]."
        )
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Error analyzing data: {str(e)}"

def analyze_stock(symbol, chat_id):
    print(f"🚀 Instantly analyzing {symbol} for user {chat_id}...")
    
    # 1. Fetch Google News
    query = f"{symbol} share news india"
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
    
    feed = feedparser.parse(rss_url)
    
    recent_news = []
    
    # 2. Filter News (Last 48 hours for manual trigger)
    for entry in feed.entries[:5]:
        if hasattr(entry, 'published_parsed'):
            news_time = datetime(*entry.published_parsed[:6])
            if datetime.now() - news_time < timedelta(hours=48):
                recent_news.append({
                    "title": entry.title,
                    "link": entry.link
                })

    if not recent_news:
        send_telegram(chat_id, f"ℹ️ **No recent news found for {symbol}.**\n(Checked last 48 hours)")
        return

    # 3. Get AI Analysis
    ai_response = get_ai_verdict(symbol, recent_news)
    
    # 4. Construct Message
    top_story = recent_news[0]
    msg = (
        f"🤖 **Instant Analysis: {symbol}**\n\n"
        f"{ai_response}\n\n"
        f"📰 **Latest Headline:**\n{top_story['title']}\n"
        f"[Read Article]({top_story['link']})"
    )
    
    send_telegram(chat_id, msg)

if __name__ == "__main__":
    # This setup allows the script to accept arguments from GitHub Actions
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Stock Symbol to analyze", required=True)
    parser.add_argument("--chat_id", help="User ID to reply to", required=True)
    args = parser.parse_args()

    analyze_stock(args.symbol, args.chat_id)
