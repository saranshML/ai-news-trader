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

# Configure AI
genai.configure(api_key=GEMINI_API_KEY)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID, 
        "text": message, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    requests.post(url, json=payload)

def get_ai_signal(stock, news_title):
    """
    Asks Gemini to act as a trader and give a Buy/Sell signal.
    """
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = (
            f"NEWS: {news_title}\n"
            f"STOCK: {stock}\n"
            "CONTEXT: You are a strict algorithmic trader. Analyze this specific news headline.\n"
            "TASK: Classify impact as BULLISH (Buy), BEARISH (Sell), or NEUTRAL (Ignore).\n"
            "CRITERIA: Look for Splits, Bonus, Big Orders, Profit Jumps, Acquisitions (Bullish). Look for Raids, Fines, Profit Drops (Bearish).\n"
            "OUTPUT FORMAT: Signal: [BUY/SELL/HOLD] | Confidence: [High/Med/Low] | Reason: [Max 10 words]."
        )
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        return "Signal: HOLD | Confidence: Low | Reason: AI Error"

def load_memory():
    # Load list of news we have already analyzed to avoid duplicates
    try:
        with open('news_memory.json', 'r') as f:
            return json.load(f)
    except:
        return []

def save_memory(memory):
    # Keep only last 1000 items
    with open('news_memory.json', 'w') as f:
        json.dump(memory[-1000:], f)

def check_market_news():
    print("🚀 Starting AI Trader...")
    
    # Load Watchlist
    with open('watchlist.txt', 'r') as f:
        stocks = [line.strip() for line in f if line.strip()]
    
    seen_news = load_memory()
    new_seen_news = list(seen_news) # Copy list to append new items
    
    for stock in stocks:
        # Search Google News RSS
        query = f"{stock} share news india"
        encoded_query = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
        
        feed = feedparser.parse(rss_url)
        
        # Check the top 2 headlines only
        for entry in feed.entries[:2]:
            title = entry.title
            link = entry.link
            pub_date = entry.published_parsed # Time struct
            
            # Skip if news is older than 24 hours
            if pub_date:
                news_time = datetime(*pub_date[:6])
                if datetime.now() - news_time > timedelta(hours=24):
                    continue

            # Create ID to prevent duplicates
            news_id = f"{stock}_{title[:30]}"
            
            if news_id in seen_news:
                continue # We already traded on this news
            
            print(f"🔎 Analyzing: {stock} - {title[:20]}...")
            
            # --- THE AI STEP ---
            ai_verdict = get_ai_signal(stock, title)
            
            # Only alert if it's NOT just generic noise
            msg = (
                f"🚨 **AI TRADE SIGNAL: {stock}**\n"
                f"{ai_verdict}\n\n"
                f"📰 *News:* {title}\n"
                f"[Read Source]({link})"
            )
            
            send_telegram(msg)
            new_seen_news.append(news_id)
            
        time.sleep(1) # Sleep to avoid Google blocking us
        
    save_memory(new_seen_news)

if __name__ == "__main__":
    check_market_news()
