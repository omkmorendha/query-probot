import os
import openai
from flask import Flask, request
from telebot import TeleBot, types
import logging
import redis
import ast
import time
from celery import Celery
from dotenv import load_dotenv

load_dotenv()


## APP SET UP
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["CELERY_BROKER_URL"] = os.environ.get(
    "REDIS_URL", "redis://localhost:6379/0"
)
app.config["CELERY_RESULT_BACKEND"] = os.environ.get(
    "REDIS_URL", "redis://localhost:6379/0"
)
redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery = Celery(app.name, broker=app.config["CELERY_BROKER_URL"])
celery.conf.update(app.config)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
URL = os.environ.get("URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
TO_EMAIL = ast.literal_eval(os.environ.get("TO_EMAIL"))

bot = TeleBot(BOT_TOKEN, threaded=True)
# bot.remove_webhook()
# time.sleep(1)
# bot.set_webhook(url=f"{URL}/{WEBHOOK_SECRET}")


@bot.message_handler(commands=["start", "restart"])
def start(message):
    """Handle /start and /restart commands."""
    message_to_send = "Welcome!\nI will send you questions for you to answer and your answers will then be sent to the appropriate team members!\nHold down the microphone to answer."
    bot.send_message(message.chat.id, message_to_send, parse_mode="Markdown")


@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    """Webhook to handle incoming updates from Telegram."""
    update = types.Update.de_json(request.data.decode("utf8"))
    bot.process_new_updates([update])
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0")
