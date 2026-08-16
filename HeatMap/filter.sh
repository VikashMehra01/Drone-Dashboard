#!/bin/sh
if [ -f .env.example ]; then
    sed -i 's/8685047479:AAH04rN8Qn6v7269wAbXCt1_rcfsM-bQ5Ro/your_telegram_bot_token_here/g' .env.example
fi
