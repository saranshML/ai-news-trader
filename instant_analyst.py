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
from PIL import Image

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
        payload = {"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown", "disable_web_page_preview": True}
        try:
            r = requests.post(url, json=payload)
            if r.status_code != 200:
                payload['parse_mode'] = ""
                requests.post(url, json=payload)
        except Exception as e:
            print(f"Telegram Error: {e}")

# --- FEATURE 1: 10% DROP SCANNER ---
def scan_for_crashes(chat_id):
    send_telegram(chat_id, "📉 **Scanning for >10% Corrections...**")
    try:
        with open('watchlist.txt', 'r') as f:
            stocks = [line.strip() + ".NS" if not line.strip().endswith('.NS') else line.strip() for line in f if line.strip()]
    except:
        send_telegram(chat_id, "❌ Error: watchlist.txt not found")
        return

    crashed_stocks = []
    for symbol in stocks:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="3mo")
            if hist.empty: continue
            
            curr = hist['Close'].iloc[-1]
            high = hist['High'].max()
            drop = ((curr - high) / high) * 100
            
            if drop <= -10:
                stable = hist['Close'].iloc[-1] > hist['Open'].iloc[-1] # Green candle today?
                crashed_stocks.append(f"**{symbol.replace('.NS','')}**\n📉 Drop: {drop:.1f}% | CMP: {int(curr)}\nStatus: {'🟢 Stabilizing' if stable else '🔴 Falling'}")
        except: continue

    if crashed_stocks:
        send_telegram(chat_id, "🚨 **OVERSOLD ALERT**\n\n" + "\n\n".join(crashed_stocks))
    else:
        send_telegram(chat_id, "✅ No stocks are down >10% from recent highs.")

# --- FEATURE 2: CHART VISION ---
def analyze_chart_image(symbol, image_url):
    try:
        yf_ticker = yf.Ticker(symbol if symbol.endswith('.NS') else f"{symbol}.NS")
        price = round(yf_ticker.history(period="1d")['Close'].iloc[-1], 2)
    except: price = "Unknown"

    print(f"👁️ Vision Analysis for {symbol}...")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(image_url, headers=headers, stream=True, timeout=10)
        img = Image.open(response.raw)

        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = (
            f"Asset: {symbol} | CMP: {price}\n"
            "Task: Identify Support Levels & Buy Zones below CMP from this chart.\n"
            "Output: Telegraphic. Fragments only.\n"
            "FORMAT:\n"
            "👁️ **VISION: {symbol}**\n"
            "💰 **CMP:** {price}\n"
            "🎯 **TARGETS:**\n1. [Price] ([Reason])\n2. [Price] ([Reason])\n"
            "🛑 **STOP:** [Price]\n"
            "⚖️ **VERDICT:** [WAIT/BUY]"
        )
        response = model.generate_content([prompt, img])
        return response.text.strip()
    except Exception as e:
        return f"❌ Vision Error: {e}"

# --- FEATURE 3: PDF ANALYZER (DUAL MODE: 3-3-3 OR FUT) ---
def analyze_pdf_report(symbol, pdf_url, mode="STANDARD"):
    print(f"📥 Analyzing PDF ({mode})...")
    try:
        # 1. Price Context
        yf_ticker = yf.Ticker(symbol if symbol.endswith('.NS') else f"{symbol}.NS")
        hist = yf_ticker.history(period="1d")
        price = round(hist['Close'].iloc[-1], 2) if not hist.empty else 0

        # 2. Download
        r = requests.get(pdf_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        f = io.BytesIO(r.content)
        reader = PdfReader(f)
        text = ""
        max_pg = 30 if mode == "FUTURE" else 15
        for i in range(min(len(reader.pages), max_pg)):
            t = reader.pages[i].extract_text()
            if t: text += t

        # 3. Select Prompt
        model = genai.GenerativeModel('gemini-2.5-pro')
        
        if mode == "FUTURE":
            # STRATEGIC OUTLOOK (Detailed)
            prompt = (
                f"CTX: STOCK {symbol} | CMP {price} | TYPE: FILING\n"
                f"DATA: {text[:90000]}\n"
                "TASK: Analyze for FUTURE GROWTH & STRATEGY.\n"
                "OUTPUT:\n"
                "🚀 **STRATEGIC OUTLOOK: {symbol}**\n"
                "1️⃣ **Long Term:** (Vision, Moat, CapEx)\n"
                "2️⃣ **Near Term:** (Guidance, Drivers)\n"
                "3️⃣ **Tone:** (Mgmt Confidence, Timelines)\n"
                "🎯 **VERDICT:** [Growth/Stable/Risk]"
            )
        else:
            # TELEGRAPHIC 3-3-3 (Optimized)
            prompt = (
                f"CTX: STOCK {symbol} | CMP {price} | TYPE: FILING\n"
                f"DATA: {text[:30000]}\n"
                "TASK: Telegraphic 3-3-3 Analysis. No filler words.\n"
                "OUTPUT:\n"
                "📊 **ANALYSIS: {symbol}**\n"
                "💰 **CMP:** {price}\n"
                "🎯 **BUY:** [Zone] | **STOP:** [Level]\n\n"
                "✅ **PROS:**\n1. [Pt]\n2. [Pt]\n3. [Pt]\n\n"
                "⚠️ **CONS:**\n1. [Pt]\n2. [Pt]\n3. [Pt]\n\n"
                "💡 **HIGHLIGHTS:**\n1. [Pt]\n2. [Pt]\n3. [Pt]\n\n"
                "⚖️ **VERDICT:** [BULL/BEAR]"
            )

        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"❌ PDF Error: {e}"

# --- FEATURE 4: STANDARD AUTO-ANALYSIS ---
def analyze_stock(symbol, chat_id, specific_url=None, mode="STANDARD"):
    # 1. SCAN COMMAND
    if symbol.upper() == "SCAN":
        scan_for_crashes(chat_id)
        return

    # 2. TARGET COMMAND (Vision)
    if mode == "TARGET" and specific_url:
        send_telegram(chat_id, f"👁️ **Reading Chart...**\n`{specific_url}`")
        analysis = analyze_chart_image(symbol, specific_url)
        send_telegram(chat_id, analysis)
        return

    # 3. PDF ANALYSIS (FUT or STANDARD)
    if specific_url and "pdf" in specific_url.lower():
        header = "🔮 **Future Outlook...**" if mode == "FUTURE" else "🔄 **Reading Doc...**"
        send_telegram(chat_id, f"{header}\n`{specific_url.split('/')[-1]}`")
        analysis = analyze_pdf_report(symbol, specific_url, mode)
        send_telegram(chat_id, analysis)
        return

    # 4. DEFAULT: NEWS + TECHNICALS
    yf_symbol = symbol if symbol.endswith('.NS') else f"{symbol}.NS"
    
    # News
    query = f"{symbol} share news india"
    rss = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    feed = feedparser.parse(rss)
    news = [e for e in feed.entries[:3] if datetime.now() - datetime(*e.published_parsed[:6]) < timedelta(hours=48)]
    
    if news:
        model = genai.GenerativeModel('gemini-2.5-flash')
        ai = model.generate_content(f"STOCK: {symbol}. NEWS: {news[0].title}. Telegraphic verdict.").text
        send_telegram(chat_id, f"📰 **NEWS: {symbol}**\n{ai}\n🔗 [Link]({news[0].link})")
        return

    # Technical Fallback
    try:
        d = yf.download(yf_symbol, period="100d", interval="1d", progress=False)
        if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.get_level_values(0)
        
        if 'Close' in d.columns:
            d = d.dropna(subset=['Close'])
            if len(d) > 50:
                cur = d['Close'].iloc[-1]
                avg = d['Close'].rolling(50).mean().iloc[-1]
                status = "BULLISH" if cur > avg else "BEARISH"
                diff = ((cur - avg) / avg) * 100
                send_telegram(chat_id, f"📉 **Tech: {symbol}**\nVerdict: {status}\nVs 50DMA: {diff:.2f}%")
            else: send_telegram(chat_id, f"ℹ️ No Data: {symbol}")
    except: send_telegram(chat_id, f"❌ Error scanning {symbol}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--chat_id", required=True)
    parser.add_argument("--url", default="")
    parser.add_argument("--mode", default="STANDARD")
    args = parser.parse_args()

    analyze_stock(args.symbol, args.chat_id, args.url, args.mode)
        
