from fastapi import FastAPI, WebSocket
import yfinance as yf
import asyncio

app = FastAPI()

@app.websocket("/ws/ltp")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    symbol = await websocket.receive_text()

    while True:
        try:
            stock = yf.Ticker(symbol)
            ltp = stock.info.get("regularMarketPrice", None)
            await websocket.send_text(str(ltp) if ltp else "N/A")
            await asyncio.sleep(2)  # adjust interval here
        except:
            await websocket.send_text("Error")
            break
