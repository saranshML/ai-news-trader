import os
import json
import time
import feedparser
import requests
import google.generativeai as genai
import urllib.parse
from datetime import datetime, timedelta

# --- CONFIGURATION ---
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']

genai.configure(api_key=GEMINI_API_KEY)

def send_telegram(message):
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
            resp = requests.post(url, json=payload)
            print(f"   --> Telegram Status: {resp.status_code}") # DEBUG PRINT
        except Exception as e:
            print(f"   --> Telegram Error: {e}")

def get_ai_signal(stock, news_title):
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = (
            f"NEWS: {news_title}\n"
            f"STOCK: {stock}\n"
            "ROLE: Algorithmic Trader.\n"
            "TASK: Analyze impact.\n"
            "OUTPUT: Signal: [BUY/SELL/HOLD] | Confidence: [High/Med] | Why: [5 words max]."
        )
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"   --> AI Error: {e}")
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
    print(f"🚀 STARTING DEBUG SCAN...")
    
    with open('watchlist.txt', 'r') as f:
        stocks = [line.strip() for line in f if line.strip()]
    
    seen_news = load_memory()
    initial_count = len(seen_news)
    
    start_time = time.time()
    
    for i, stock in enumerate(stocks):
        if (time.time() - start_time) > 270: 
            print("⏳ Time Limit Reached.")
            break

        print(f"\n[{i+1}/{len(stocks)}] Checking {stock}...") # DEBUG PRINT

        query = f"{stock} share news india"
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
        
        try:
            feed = feedparser.parse(rss_url)
        except:
            print("   --> Failed to parse feed")
            continue
        
        if not feed.entries:
            print("   --> No news found in RSS.")
            continue

        for entry in feed.entries[:3]: # Check top 3
            title = entry.title
            link = entry.link
            
            # Age Check
            if hasattr(entry, 'published_parsed'):
                news_time = datetime(*entry.published_parsed[:6])
                age_hours = (datetime.now() - news_time).total_seconds() / 3600
                if age_hours > 24:
                    print(f"   --> Skipped: Too old ({age_hours:.1f} hours ago) - {title[:30]}...")
                    continue
            
            # Duplicate Check
            news_id = f"{stock}_{title[:40]}"
            if news_id in seen_news:
                print(f"   --> Skipped: Already in Memory - {title[:30]}...")
                continue 
            
            # AI Check
            print(f"   ⚡ Sending to AI: {title[:40]}...")
            ai_verdict = get_ai_signal(stock, title)
            print(f"      AI VERDICT: {ai_verdict}") # DEBUG PRINT
            
            # Telegram Trigger
            # Note: I removed the "Buy/Sell" filter so you ALWAYS get a message for testing
            msg = (
                f"🚨 **{stock}**\n"
                f"{ai_verdict}\n"
                f"📰 {title}\n"
                f"[Source]({link})"
            )
            send_telegram(msg)
            
            seen_news.add(news_id)
            time.sleep(1.5)

    if len(seen_news) > initial_count:
        save_memory(seen_news)
        print("\n✅ Memory updated.")
    else:
        print("\nℹ️ No new items to save.")

if __name__ == "__main__":
    check_market_news()
