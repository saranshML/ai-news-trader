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

# --- TELEGRAM HELPER ---
def send_telegram(chat_id, message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    chunk_size = 4000
    for i in range(0, len(message), chunk_size):
        chunk = message[i:i+chunk_size]
        payload = {
            "chat_id": chat_id, "text": chunk, "parse_mode": "Markdown", "disable_web_page_preview": True
        }
        try:
            r = requests.post(url, json=payload)
            if r.status_code != 200:
                payload['parse_mode'] = ""
                requests.post(url, json=payload)
        except Exception as e:
            print(f"Telegram Error: {e}")

# --- PDF ANALYZER (DUAL MODE) ---
def analyze_pdf_report(symbol, pdf_url, mode="STANDARD"):
    print(f"📥 Fetching PDF & Price Data (Mode: {mode})...")
    try:
        # 1. Price Context
        yf_ticker = yf.Ticker(symbol if symbol.endswith('.NS') else f"{symbol}.NS")
        price_data = yf_ticker.history(period="1d")
        current_price = round(price_data['Close'].iloc[-1], 2) if not price_data.empty else 0

        # 2. Download PDF
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(pdf_url, headers=headers, timeout=15)
        r.raise_for_status()
        
        # 3. Extract Text
        f = io.BytesIO(r.content)
        reader = PdfReader(f)
        text_content = ""
        max_pages = min(len(reader.pages), 30) # 30 pages for deep reading
        for i in range(max_pages):
            text = reader.pages[i].extract_text()
            if text: text_content += text

        # 4. Select Prompt Based on Mode
        model = genai.GenerativeModel('gemini-2.5-flash') 
        
        if mode == "FUTURE":
            # --- PROMPT A: STRATEGIC FUTURE OUTLOOK ---
            prompt = (
                f"CTX: STOCK {symbol} | CMP {current_price} | DOC TYPE: Corporate Filing\n"
                f"DOC TEXT (First {max_pages} pgs): {text_content[:90000]}\n"
                "ROLE: Senior Growth Strategist.\n"
                "TASK: Analyze specifically for FUTURE PROSPECTS & GROWTH STRATEGY.\n"
                "INSTRUCTIONS: Detect doc type (Annual/Quarterly/Concall) and extract forward-looking info.\n\n"
                "OUTPUT FORMAT (Strictly):\n"
                "🚀 **STRATEGIC FUTURE OUTLOOK: {symbol}**\n\n"
                "1️⃣ **Strategic Outlook (Long Term):**\n"
                "(Focus: Vision, Moat, CapEx 3-5yrs)\n\n"
                "2️⃣ **Near-Term Guidance:**\n"
                "(Focus: Revenue/Margin Forecasts, Growth Drivers)\n\n"
                "3️⃣ **Management Tone & Specifics:**\n"
                "(Focus: Confidence level, RoCE targets, Project Timelines)\n\n"
                "🎯 **GROWTH VERDICT:** [High Growth / Stable / Risk] | [Confidence %]"
            )
        else:
            # --- PROMPT B: STANDARD 3-3-3 RULE (Telegraphic) ---
            prompt = (
                f"CTX: STOCK {symbol} | CMP {current_price} | TYPE: FILING\n"
                f"DATA: {text_content[:30000]}\n"
                "ROLE: Quant Algo. MODE: Telegraphic. No filler words.\n"
                "TASK: 3-3-3 RULE. List exactly 3 PROS, 3 CONS, 3 HIGHLIGHTS.\n"
                "STYLE: Fragment sentences. Data dense.\n\n"
                "OUTPUT FORMAT:\n"
                "📊 **ANALYSIS: {symbol}**\n"
                "💰 **CMP:** {current_price}\n"
                "🎯 **BUY:** [Range] | **STOP:** [Level]\n\n"
                "✅ **PROS:**\n1. [Point]\n2. [Point]\n3. [Point]\n\n"
                "⚠️ **CONS:**\n1. [Point]\n2. [Point]\n3. [Point]\n\n"
                "💡 **HIGHLIGHTS:**\n1. [Point]\n2. [Point]\n3. [Point]\n\n"
                "⚖️ **VERDICT:** [BULL/BEAR] | [Conf%]"
            )
        
        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        return f"❌ Analysis Failed: {str(e)}"

# --- STANDARD ANALYZERS ---
def get_ai_verdict(stock, content):
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"STOCK: {stock}. DATA: {content}. OUTPUT: Telegraphic style. Verdict: [BUY/SELL] | Reason."
        response = model.generate_content(prompt)
        return response.text.strip()
    except:
        return "Error in AI."

def check_for_quarterly_results(symbol):
    return None # Simplified for this update

def analyze_stock(symbol, chat_id, specific_url=None, mode="STANDARD"):
    # --- PATH A: PDF DEEP DIVE ---
    if specific_url and len(specific_url) > 5:
        msg_header = "🔮 **Analyzing Future Outlook...**" if mode == "FUTURE" else "🔄 **Processing Doc...**"
        send_telegram(chat_id, f"{msg_header}\n`{specific_url.split('/')[-1]}`")
        
        analysis = analyze_pdf_report(symbol, specific_url, mode)
        send_telegram(chat_id, analysis)
        return

    # --- PATH B: AUTO SCAN (Standard 3-3-3 logic applies here) ---
    yf_symbol = symbol if symbol.endswith('.NS') else f"{symbol}.NS"
    
    # Simple News Check
    query = f"{symbol} share news india"
    rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    feed = feedparser.parse(rss_url)
    
    recent_news = []
    for entry in feed.entries[:3]:
        if hasattr(entry, 'published_parsed'):
            if datetime.now() - datetime(*entry.published_parsed[:6]) < timedelta(hours=48):
                recent_news.append(entry)

    if recent_news:
        ai_resp = get_ai_verdict(symbol, recent_news[0]['title'])
        send_telegram(chat_id, f"📰 **NEWS: {symbol}**\n{ai_resp}\n🔗 [Link]({recent_news[0]['link']})")
        return

    # Technical Fallback
    try:
        data = yf.download(yf_symbol, period="100d", interval="1d", progress=False)
        if isinstance(data.columns, pd.MultiIndex): data.columns = data.columns.get_level_values(0)
        
        if 'Close' in data.columns:
            data = data.dropna(subset=['Close'])
            if len(data) > 50:
                cur = data['Close'].iloc[-1]
                dma = data['Close'].rolling(50).mean().iloc[-1]
                status = "BULLISH" if cur > dma else "BEARISH"
                diff = ((cur - dma) / dma) * 100
                msg = f"📉 **Tech:** {symbol}\nStart: {status}\nVs 50DMA: {diff:.2f}%"
                send_telegram(chat_id, msg)
            else:
                send_telegram(chat_id, f"ℹ️ No Data: {symbol}")
        else:
            send_telegram(chat_id, f"❌ Data Error: {symbol}")
    except Exception as e:
        send_telegram(chat_id, f"❌ Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--chat_id", required=True)
    parser.add_argument("--url", default="", help="Optional PDF URL")
    parser.add_argument("--mode", default="STANDARD", help="Analysis Mode: STANDARD or FUTURE")
    args = parser.parse_args()

    analyze_stock(args.symbol, args.chat_id, args.url, args.mode)
