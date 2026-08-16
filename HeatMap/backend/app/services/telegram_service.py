import json
import urllib.request
import urllib.error
import asyncio
from app.config import settings
import logging

logger = logging.getLogger(__name__)

async def broadcast_alert(message: str) -> bool:
    """
    Sends a Markdown-formatted message to all configured Telegram Chat IDs.
    """
    token = settings.TELEGRAM_BOT_TOKEN
    chat_ids_str = settings.TELEGRAM_CHAT_IDS
    
    if not token or not chat_ids_str:
        logger.warning("Telegram Bot Token or Chat IDs missing in config. Skipping broadcast.")
        return False
        
    chat_ids = [cid.strip() for cid in chat_ids_str.split(",") if cid.strip()]
    if not chat_ids:
        logger.warning("No valid Chat IDs found for Telegram broadcast.")
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    headers = {"Content-Type": "application/json"}
    
    success = True
    for chat_id in chat_ids:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        
        try:
            req = urllib.request.Request(
                url, 
                data=json.dumps(payload).encode('utf-8'),
                headers=headers, 
                method='POST'
            )
            
            # Using asyncio.to_thread so urllib doesn't block the FastAPI async event loop
            await asyncio.to_thread(urllib.request.urlopen, req)
            logger.info(f"Broadcasted Telegram alert to {chat_id}")
            
        except urllib.error.URLError as e:
            logger.error(f"Failed to send Telegram alert to {chat_id}: {e}")
            success = False
            
    return success
