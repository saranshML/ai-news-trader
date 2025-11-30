import os
import argparse
import feedparser
import requests
import google.generativeai as genai
import urllib.parse
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import json
import io
from pypdf import PdfReader

# --- CONFIGURATION ---
BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']

genai.configure(api_key=GEMINI_API_KEY)

# --- TELEGRAM HELPER (Now with Message Splitting) ---
def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    # Telegram limit is 4096 chars. We chunk at 4000 to be safe.
    chunk_size = 4000
    
    for i in range(0, len(message), chunk_size):
        chunk = message[i:i+chunk_size]
        payload = {
            "chat_id": chat_id, 
            "text": chunk, 
            "parse_mode": "Markdown", 
            "disable_web_page_preview": True
        }
        try:
            # Try sending with Markdown
            response = requests.post(url, json=payload)
            # If failed (likely due to AI using special chars like * or _ incorrectly)
            if response.status_code != 200:
                payload['parse_mode'] = "" # Fallback to Plain Text
                requests.post(url, json=payload)
        except Exception as e:
            print(f"Telegram Error: {e}")

# --- FEATURE 1: PDF ANALYZER (Strict 3-Point Limit) ---
def analyze_pdf_report(symbol, pdf_url):
    print(f"📥 Downloading PDF from {pdf_url}...")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(pdf_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        f = io.BytesIO(response.content)
        reader = PdfReader(f)
        text_content = ""
        
        # Limit pages to speed up processing
        max_pages = min(len(reader.pages), 20) 
        for i in range(max_pages):
            text = reader.pages[i].extract_text()
            if text:
                text_content += text
            
        print(f"📄 Extracted {len(text_content)} chars.")

        # Using 2.5 Pro as requested
        model = genai.GenerativeModel('gemini-2.5-pro') 
        
        # --- THE UPDATED STRICT PROMPT ---
        prompt = (
            f"STOCK: {symbol}\n"
            f"DOCUMENT TEXT (First {max_pages} pages):\n{text_content}\n\n"
            "ROLE: Senior Equity Research Analyst.\n"
            "TASK: Analyze this Corporate Filing.\n"
            "CONSTRAINT: You must provide EXACTLY 3 bullet points per section. Keep them concise.\n\n"
            "OUTPUT FORMAT:\n"
            "📊 **Analysis of Filing**\n\n"
            "✅ **Top 3 Pros:**\n1. [Strongest Point]\n2. [Point 2]\n3. [Point 3]\n\n"
            "⚠️ **Top 3 Cons/Risks:**\n1. [Biggest Risk]\n2. [Point 2]\n3. [Point 3]\n\n"
            "💡 **3 Key Highlights:**\n1. [Financial Metric]\n2. [Future Guidance]\n3. [Strategic Update]\n\n"
            "🎯 **Verdict:** [BULLISH / BEARISH / NEUTRAL]"
        )
        
        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        return f"❌ PDF Error: {str(e)}"

# --- FEATURE 2: STANDARD ANALYZER ---
def get_ai_verdict(stock, context_type, content):
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        if context_type == "FINANCIALS":
            prompt = f"STOCK: {stock}. FINANCIALS: {content}. Analyze YOY Revenue/PAT. Verdict: [BULLISH/BEARISH] | Pros | Cons."
        else:
            prompt = f"STOCK: {stock}. NEWS: {content}. Impact Analysis. Verdict: [BUY/SELL] | Summary."
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"AI Error: {str(e)}"

# --- DATA FETCHERS ---
def check_for_quarterly_results(symbol):
    query = f"{symbol} quarterly results published"
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
    feed = feedparser.parse(rss_url)
    
    for entry in feed.entries:
        if hasattr(entry, 'published_parsed'):
            news_time = datetime(*entry.published_parsed[:6])
            if datetime.now() - news_time < timedelta(days=7):
                screener_url = f"https://www.screener.in/company/{symbol.split('.')[0]}/"
                try:
                    r = requests.get(screener_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                    dfs = pd.read_html(r.text)
                    if len(dfs) > 1:
                        latest_results = dfs[1].iloc[:, -1].to_dict()
                        return f"Stock: {symbol}. Latest Results: {json.dumps(latest_results)}"
                except:
                    pass
    return None

def analyze_stock(symbol, chat_id, specific_url=None):
    # --- PATH A: URL PROVIDED ---
    if specific_url and len(specific_url) > 5:
        send_telegram(chat_id, f"🔄 **Reading Document...**\n{specific_url}")
        analysis = analyze_pdf_report(symbol, specific_url)
        send_telegram(chat_id, analysis)
        return

    # --- PATH B: STANDARD AUTO-ANALYSIS ---
    yf_symbol = symbol if symbol.endswith('.NS') else f"{symbol}.NS"
    clean_symbol = symbol.split('.')[0]

    # 1. Financials Check
    financial_data = check_for_quarterly_results(clean_symbol)
    if financial_data:
        ai_resp = get_ai_verdict(symbol, "FINANCIALS", financial_data)
        send_telegram(chat_id, f"💰 **QTR RESULTS: {symbol}**\n\n{ai_resp}")
        return

    # 2. News Check
    query = f"{symbol} share news india"
    encoded_query = urllib.parse.quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-IN&gl=IN&ceid=IN:en"
    feed = feedparser.parse(rss_url)
    
    recent_news = []
    for entry in feed.entries[:3]:
        if hasattr(entry, 'published_parsed'):
            if datetime.now() - datetime(*entry.published_parsed[:6]) < timedelta(hours=48):
                recent_news.append({"title": entry.title, "link": entry.link})

    if recent_news:
        top_story = recent_news[0]
        ai_resp = get_ai_verdict(symbol, "NEWS", top_story['title'])
        send_telegram(chat_id, f"📰 **NEWS: {symbol}**\n{ai_resp}\n🔗 [Link]({top_story['link']})")
        return

    # 3. Technical Fallback
    try:
        data = yf.download(yf_symbol, period="100d", interval="1d", progress=False)
        if isinstance(data.columns, pd.MultiIndex): 
            data.columns = data.columns.get_level_values(0)
            
        if 'Close' not in data.columns:
            send_telegram(chat_id, f"❌ YF Error: Missing 'Close' column.")
            return

        data = data.dropna(subset=['Close'])
        if len(data) > 50:
            cur = data['Close'].iloc[-1]
            dma = data['Close'].rolling(50).mean().iloc[-1]
            status = "BULLISH" if cur > dma else "BEARISH"
            diff = ((cur - dma) / dma) * 100
            msg = f"📉 **Technical: {symbol}**\nVerdict: {status}\nPrice vs 50DMA: {diff:.2f}%"
            send_telegram(chat_id, msg)
        else:
            send_telegram(chat_id, f"ℹ️ No Data found for {symbol}")
    except Exception as e:
        send_telegram(chat_id, f"❌ Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--chat_id", required=True)
    parser.add_argument("--url", default="", help="Optional PDF URL")
    args = parser.parse_args()

    analyze_stock(args.symbol, args.chat_id, args.url)
