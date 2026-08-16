import os
import urllib.request
import urllib.error
import json

def get_chat_ids():
    # Attempt to read the .env file manually so we don't need the python-dotenv package
    token = None
    try:
        with open(".env", "r") as f:
            for line in f:
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
    except FileNotFoundError:
        pass

    if not token or token == "your_botfather_token_here":
        print("Error: TELEGRAM_BOT_TOKEN is missing or not set in .env")
        print("1. Go to Telegram and message @BotFather to create a bot.")
        print("2. Copy the HTTP API Token.")
        print("3. Paste it into your backend/.env as TELEGRAM_BOT_TOKEN=...")
        token = input("\nAlternatively, you can paste the token here now to just run the script: ").strip()
        if not token:
            return

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    
    print("\n[SkyWatch Telegram Helper]")
    print("Checking for recent messages...\n")
    print("If this is your first time, please open your new bot in Telegram and send it a message like 'Hello'!")
    
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            if not data.get("ok"):
                print("Error from Telegram API:", data)
                return
                
            results = data.get("result", [])
            if not results:
                print("No messages found! Make sure you actually send a message to your bot from your Telegram app.")
                return
                
            print("=== Found Users ===")
            seen = set()
            for update in results:
                message = update.get("message")
                if message:
                    chat = message.get("chat", {})
                    chat_id = chat.get("id")
                    username = chat.get("username", "Unknown")
                    first_name = chat.get("first_name", "")
                    
                    if chat_id and chat_id not in seen:
                        seen.add(chat_id)
                        print(f"User: {first_name} (@{username})")
                        print(f"Chat ID: {chat_id}")
                        print("-" * 30)
                        
            print("\nCopy the Chat ID(s) above and paste them into your backend/.env file:")
            print(f"TELEGRAM_CHAT_IDS={','.join(str(i) for i in seen)}")
            print("\nThen restart your backend server!")
            
    except urllib.error.URLError as e:
        print(f"Failed to connect to Telegram: {e}")
        
if __name__ == "__main__":
    get_chat_ids()
