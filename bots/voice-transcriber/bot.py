import os
import tempfile
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
import httpx

BOT_TOKEN = os.environ["BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправь мне голосовое сообщение — я верну текст 🎤")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("⏳ Распознаю...")

    voice = update.message.voice or update.message.audio
    file = await context.bot.get_file(voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        tmp_path = f.name
        await file.download_to_drive(tmp_path)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            with open(tmp_path, "rb") as audio:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    files={"file": ("voice.ogg", audio, "audio/ogg")},
                    data={"model": "whisper-1"},
                )
            result = resp.json()
            text = result.get("text", "Ошибка распознавания")
    except Exception as e:
        text = f"Ошибка: {e}"
    finally:
        os.unlink(tmp_path)

    await msg.edit_text(f"📝 {text}")


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    print("Bot started!")
    app.run_polling()


if __name__ == "__main__":
    main()
