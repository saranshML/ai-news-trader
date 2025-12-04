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
from PIL import Image # NEW: For handling Chart Images

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

# --- FEATURE 1: 10% DROP SCANNER (Mathematical) ---
def scan_for_crashes(chat_id):
    """Scans watchlist for stocks down >10% from 52-Week High"""
    send_telegram(chat_id, "📉 **Starting 10% Drop Scan...**")
    
    # 1. Load Watchlist
    try:
        with open('watchlist.txt', 'r') as f:
            stocks = [line.strip() + ".NS" if not line.strip().endswith('.NS') else line.strip() for line in f if line.strip()]
    except:
        send_telegram(chat_id, "❌ Error: Could not read watchlist.txt")
        return

    # 2. Bulk Fetch Data (Faster)
    crashed_stocks = []
    
    for symbol in stocks:
        try:
            # Get last 3 months of data
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="3mo")
            
            if hist.empty: continue
            
            current_price = hist['Close'].iloc[-1]
            recent_high = hist['High'].max()
            
            drop_percentage = ((current_price - recent_high) / recent_high) * 100
            
            # CRITERIA: Down at least 10%
            if drop_percentage <= -10:
                # Check for "Stop" in fall (Green candle today or flat last 3 days)
                is_stabilizing = False
                last_3_days = hist['Close'].tail(3)
                if hist['Close'].iloc[-1] > hist['Open'].iloc[-1]: # Today is Green
                    is_stabilizing = True
                
                crashed_stocks.append({
                    "symbol": symbol.replace('.NS', ''),
                    "cmp": int(current_price),
                    "high": int(recent_high),
                    "drop": round(drop_percentage, 1),
                    "stable": is_stabilizing
                })
        except:
            continue

    # 3. Report Results
    if not crashed_stocks:
        send_telegram(chat_id, "✅ **Scan Complete:** No stocks are down >10% from recent highs.")
    else:
        msg = "🚨 **OVERSOLD ALERT (Down >10%)**\n\n"
        for s in crashed_stocks:
            status = "🟢 Stabilizing" if s['stable'] else "🔴 Still Falling"
            msg += f"**{s['symbol']}**\n📉 Drop: {s['drop']}%\n💰 CMP: {s['cmp']} (High: {s['high']})\nStauts: {status}\n\n"
        send_telegram(chat_id, msg)

# --- FEATURE 2: CHART VISION ANALYST (Visual) ---
def analyze_chart_image(symbol, image_url):
    print(f"👁️ Analyzing Chart for {symbol}...")
    try:
        # 1. Get Price Context
        yf_ticker = yf.Ticker(symbol if symbol.endswith('.NS') else f"{symbol}.NS")
        price_data = yf_ticker.history(period="1d")
        current_price = round(price_data['Close'].iloc[-1], 2) if not price_data.empty else "Unknown"

        # 2. Download Image
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(image_url, headers=headers, stream=True, timeout=10)
        response.raise_for_status()
        
        # Load image into Pillow
        img = Image.open(response.raw)

        # 3. Vision Prompt (Gemini 1.5 Flash is best for Vision)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = (
            f"You are a Technical Analyst. This is a chart for {symbol}. Current Price (CMP): {current_price}.\n"
            "Your Task: Identify the BEST BUY ZONES below the current price.\n"
            "Look for:\n"
            "1. Horizontal Support levels (previous bounce zones).\n"
            "2. Trendline support.\n"
            "3. 200 EMA support (if visible).\n\n"
            "OUTPUT FORMAT (Telegraphic):\n"
            "👁️ **CHART VISION: {symbol}**\n"
            "💰 **CMP:** {current_price}\n\n"
            "🎯 **TARGET BUY ZONES:**\n"
            "1. **Zone 1 (Aggressive):** [Price] - [Reason: e.g., 50 EMA]\n"
            "2. **Zone 2 (Safe):** [Price] - [Reason: e.g., Major Support]\n"
            "3. **Zone 3 (Deep):** [Price] - [Reason: e.g., 200 EMA/Trendline]\n\n"
            "🛑 **STOP LOSS:** [Price Level] (Below key structure)\n"
            "⚖️ **VERDICT:** [WAIT FOR DIP / BUY NOW / AVOID]"
        )
        
        # Pass both text and image to Gemini
        response = model.generate_content([prompt, img])
        return response.text.strip()

    except Exception as e:
        return f"❌ Vision Error: {str(e)}"

# --- EXISTING PDF & TEXT ANALYZERS ---
def analyze_pdf_report(symbol, pdf_url, mode="STANDARD"):
    # ... (Keep your existing PDF logic exactly as it was) ...
    # For brevity, I am assuming you paste your previous 'analyze_pdf_report' function here.
    # If you need me to paste the full block again, let me know.
    return "PDF Analysis Placeholder (Paste previous logic here)"

def get_ai_verdict(stock, content):
    # ... (Keep existing logic) ...
    return "News Analysis Placeholder"

# --- MAIN CONTROLLER (Updated for TARGET command) ---
def analyze_stock(symbol, chat_id, specific_url=None, mode="STANDARD"):
    
    # 1. SPECIAL COMMAND: SCAN
    if symbol.upper() == "SCAN":
        scan_for_crashes(chat_id)
        return

    # 2. TARGET COMMAND (Chart Analysis)
    if mode == "TARGET" and specific_url:
        send_telegram(chat_id, f"👁️ **Reading Chart...**\n`{specific_url}`")
        analysis = analyze_chart_image(symbol, specific_url)
        send_telegram(chat_id, analysis)
        return

    # 3. PDF ANALYSIS (Existing)
    if specific_url and "pdf" in specific_url.lower():
        # ... (Call analyze_pdf_report) ...
        pass

    # 4. STANDARD ANALYSIS (News/Tech)
    # ... (Keep existing standard logic) ...

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--chat_id", required=True)
    parser.add_argument("--url", default="", help="Optional URL")
    parser.add_argument("--mode", default="STANDARD", help="Analysis Mode")
    args = parser.parse_args()

    analyze_stock(args.symbol, args.chat_id, args.url, args.mode)
                              
