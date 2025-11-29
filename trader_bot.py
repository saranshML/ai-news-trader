import os
import json
import time
import feedparser
import requests
import google.generativeai as genai
import urllib.parse
from datetime import datetime, timedelta

# --- CONFIGURATION ---
# The script still looks for the standard names, 
# but the YAML file above feeds your "KEY2" into these variables.
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']

genai.configure(api_key=GEMINI_API_KEY)

def send_telegram(message):
    # Handles multiple Chat IDs if you have them
    ids = CHAT_ID.split(',')
    for user_id in ids:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": user_id.strip(), 
            "text": message, 
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        try:
            requests.post(url, json=payload)
        except:
            pass

def get_ai_signal(stock, news_title):
    try:
        # USING GEMINI 2.5 FLASH (Fast & Cheap)
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = (
            f"NEWS: {news_title}\n"
            f"STOCK: {stock}\n"
            "ROLE: Algorithmic Trader.\n"
            "TASK: Analyze impact on stock price.\n"
            "LABELS: [BUY] (Positive: Split, Bonus, Expansion, Big Order). [SELL] (Negative: Fraud, Raid, Loss, Resignation). [NEUTRAL] (Generic).\n"
            "OUTPUT: Signal: [BUY/SELL/HOLD] | Confidence: [High/Med] | Why: [5 words max]."
        )
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        return "Signal: HOLD | Confidence: Low | Why: Error"

def load_memory():
    try:
        with open('news_memory.json', 'r') as f:
            return set(json.load(f))
    except:
        return set()

def save_memory(memory_set):
    recent_items = list(memory_set)[-2000:]
    with open('news_memory.json', 'w') as f:
        json.dump(recent_items, f)

def check_market_news():
    print(f"🚀 Scanning 50 Stocks (High Intensity Mode)...")
    
    with open('watchlist.txt', 'r') as f:
        stocks = [line.strip() for line in f if line.strip()]
    
    seen_news = load_memory()
    initial_count = len(seen_news)
    
    # Timer to protect GitHub Minutes (Stops after 4.5 mins)
    start_time = time.time()
    
    for stock in stocks:
        if (time.time() - start_time) > 270: 
            print("⏳ Time Limit Reached (Saving Quota).")
            break

        query = f"{stock} share news india"
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
        
        try:
            feed = feedparser.parse(rss_url)
        except:
            continue
        
        # DEEP SCAN: Check Top 5 Headlines (Using your 80% Gemini Capacity)
        for entry in feed.entries[:5]:
            title = entry.title
            link = entry.link
            
            # Age Check (<24h)
            if hasattr(entry, 'published_parsed'):
                news_time = datetime(*entry.published_parsed[:6])
                if datetime.now() - news_time > timedelta(hours=24):
                    continue
            
            # Duplicate Check
            news_id = f"{stock}_{title[:40]}"
            if news_id in seen_news:
                continue 
            
            # AI Check
            print(f"⚡ Analyzing: {stock}...")
            ai_verdict = get_ai_signal(stock, title)
            
            # Filter: Alert on BUY/SELL, Ignore HOLD
            if "BUY" in ai_verdict.upper() or "SELL" in ai_verdict.upper():
                msg = (
                    f"🚨 **{stock}**\n"
                    f"{ai_verdict}\n"
                    f"📰 {title}\n"
                    f"[Source]({link})"
                )
                send_telegram(msg)
            
            seen_news.add(news_id)
            time.sleep(2) # Throttle to stay within API rate limits

    if len(seen_news) > initial_count:
        save_memory(seen_news)
        print("✅ Memory updated.")

if __name__ == "__main__":
    check_market_news()
