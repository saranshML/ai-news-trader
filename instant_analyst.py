import os
import argparse
import feedparser
import requests
import google.generativeai as genai
import urllib.parse
from datetime import datetime, timedelta
import yfinance as yf # NEW: For fast technical data

# --- CONFIGURATION ---
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']

# Configure AI
genai.configure(api_key=GEMINI_API_KEY)

# --- TELEGRAM HELPER ---
def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id, 
        "text": message, 
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    requests.post(url, json=payload)

# --- AI ANALYZER ---
def get_ai_verdict(stock, context_type, content):
    """Analyzes content (news or financial figures) and gives a verdict."""
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        if context_type == "FINANCIALS":
            prompt = (
                f"STOCK: {stock}. You are analyzing published quarterly results. "
                f"FINANCIALS: {content}\n"
                "TASK: Analyze the YOY growth/decline in Revenue and PAT. "
                "Output: Verdict: [BULLISH/BEARISH/NEUTRAL] | Pros: [3 points] | Cons: [3 points]."
            )
        else: # News headlines
            prompt = (
                f"STOCK: {stock}. NEWS: {content}\n"
                "TASK: Analyze market impact. Output: Verdict: [BUY/SELL/HOLD] | Summary: [One sentence reason]."
            )

        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"AI Analysis Error: {str(e)}"

# --- DATA FETCHING FUNCTIONS ---

def check_for_quarterly_results(symbol):
    # Search for latest results announced (simulating check on NSE/BSE announcements)
    query = f"{symbol} quarterly results published"
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
    
    feed = feedparser.parse(rss_url)
    
    # Check if a results announcement was made in the last 7 days
    for entry in feed.entries:
        if hasattr(entry, 'published_parsed'):
            news_time = datetime(*entry.published_parsed[:6])
            if datetime.now() - news_time < timedelta(days=7):
                
                # If announcement found, scrape the screener page for the numbers
                # This is the most reliable way to get structured data without PDF parsing
                screener_url = f"https://www.screener.in/company/{symbol.split('.')[0]}/"
                headers = {"User-Agent": "Mozilla/5.0"}
                try:
                    r = requests.get(screener_url, headers=headers, timeout=5)
                    r.raise_for_status() # Raise error for bad status
                    
                    # Look for the 'Quarterly Results' table (often the second table)
                    dfs = pd.read_html(r.text)
                    if len(dfs) > 1:
                        # Extract the latest column (the latest quarter)
                        latest_results = dfs[1].iloc[:, -1].to_dict()
                        # Format for AI analysis
                        return f"Stock: {symbol}. Latest Quarter Results: {json.dumps(latest_results)}"
                except Exception as e:
                    print(f"Error scraping Screener: {e}")
                    return None
    return None

def analyze_stock(symbol, chat_id):
    # Ticker needs the .NS suffix for yfinance
    yf_symbol = symbol if symbol.endswith('.NS') else f"{symbol}.NS"
    
    # --- 1. QUARTERLY RESULTS CHECK (Highest Priority) ---
    financial_data = check_for_quarterly_results(symbol.split('.')[0]) # Pass symbol without .NS
    
    if financial_data:
        # A. Analyze Financials
        ai_response = get_ai_verdict(symbol, "FINANCIALS", financial_data)
        
        msg = (f"💰 **QTR RESULTS ANALYSIS: {symbol}**\n\n{ai_response}")
        send_telegram(chat_id, msg)
        return

    # --- 2. NEWS HEADLINES CHECK (Second Priority) ---
    query = f"{symbol} share news india"
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
    feed = feedparser.parse(rss_url)
    
    recent_news = []
    
    for entry in feed.entries[:3]:
        if hasattr(entry, 'published_parsed'):
            news_time = datetime(*entry.published_parsed[:6])
            if datetime.now() - news_time < timedelta(hours=48):
                recent_news.append({"title": entry.title, "link": entry.link})

    if recent_news:
        # B. Analyze News
        top_story = recent_news[0]
        ai_response = get_ai_verdict(symbol, "NEWS", top_story['title'])
        
        msg = (
            f"📰 **BREAKING NEWS: {symbol}**\n"
            f"{ai_response}\n\n"
            f"🔗 [Read Headline]({top_story['link']})"
        )
        send_telegram(chat_id, msg)
        return

   # --- 3. TECHNICAL FALLBACK CHECK (Lowest Priority) ---
    try:
        # Ticker check is inside the function now, so we run the download
        data = yf.download(yf_symbol, period="100d", interval="1d", progress=False)
        
        # Check if the downloaded data is empty (most common failure point)
        if data.empty or data['Close'].isnull().all():
             send_telegram(chat_id, f"❌ CRITICAL ERROR:\nSymbol: {symbol} has no recent data in yfinance or data is corrupted.")
             return
            
        current_price = data['Close'].iloc[-1]
        dma_50 = data['Close'].rolling(window=50).mean().iloc[-1]
        
        # --- Continue with the original logic ---
        status = "BULLISH" if current_price > dma_50 else "BEARISH"
        diff_pct = ((current_price - dma_50) / dma_50) * 100
        
        msg = (f"📉 **Technical Status: {symbol}**\n"
               f"Verdict: {status} (No News Found)\n"
               f"Price is {abs(diff_pct):.2f}% {'above' if diff_pct > 0 else 'below'} 50 DMA.")
        send_telegram(chat_id, msg)
        
    except Exception as e:
        # DEBUG: Send the detailed exception error message back to the user
        send_telegram(chat_id, f"❌ CRITICAL ERROR (YFinance):\nSymbol: {yf_symbol}\nError Details: {str(e)}")
        return


if __name__ == "__main__":
    import json # Import json locally for the script's main run
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Stock Symbol to analyze", required=True)
    parser.add_argument("--chat_id", help="User ID to reply to", required=True)
    args = parser.parse_args()

    # Pass the NSE code without the .NS suffix to the scraper
    analyze_stock(args.symbol, args.chat_id)
