import os
import openai
from flask import Flask, request
from telebot import TeleBot, types
import logging
import redis
import ast
import time
import ffmpeg
from celery import Celery
from dotenv import load_dotenv

load_dotenv()

# APP SET UP
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
redis_client = redis.StrictRedis.from_url(redis_url)

celery = Celery(app.name, broker=app.config["CELERY_BROKER_URL"])
celery.conf.update(app.config)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
URL = os.environ.get("URL")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET")
TO_EMAIL = ast.literal_eval(os.environ.get("TO_EMAIL"))

bot = TeleBot(BOT_TOKEN, threaded=True)

questions = [
    "What is your name?",
    "What is your state, city, and zip code?",
    "What is your preferred contact number?",
]


def save_response(chat_id, key, value):
    responses = redis_client.hgetall(chat_id) or {}
    responses[key] = value
    redis_client.hmset(chat_id, responses)


@bot.message_handler(commands=["start", "restart"])
def start(message):
    """Handle /start and /restart commands."""
    message_to_send = "Welcome!\nI will send you questions for you to answer and your answers will then be sent to the appropriate team members!\nHold down the microphone to answer."
    bot.send_message(message.chat.id, message_to_send, parse_mode="Markdown")
    bot.send_message(message.chat.id, questions[0], parse_mode="Markdown")


@bot.message_handler(content_types=["document", "audio", "voice", "text"])
def handle_responses(message):
    """Handle text and audio responses."""
    chat_id = message.chat.id
    responses = redis_client.hgetall(chat_id) or {}

    if not responses:
        current_question = 0
    else:
        current_question = len(responses)

    if current_question < len(questions):
        if message.content_type == "text":
            response = message.text
            save_response(chat_id, f"question_{current_question}", response)
            next_question = current_question + 1
            if next_question < len(questions):
                bot.send_message(chat_id, questions[next_question], parse_mode="Markdown")
            else:
                bot.send_message(chat_id, "Thank you! All your responses have been recorded.")
        elif message.content_type in ["audio", "voice"]:
            audio_file = message.audio or message.voice
            file_info = bot.get_file(audio_file.file_id)
            file_path = f"downloads/{audio_file.file_unique_id}.{file_info.file_path.split('.')[-1]}"
            bot.reply_to(message, "Please wait while we process the file")
            download_and_process.delay(file_info.file_path, file_path, chat_id, current_question)
    else:
        bot.send_message(chat_id, "All questions have been answered. Thank you!")


@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    """Webhook to handle incoming updates from Telegram."""
    update = types.Update.de_json(request.data.decode("utf8"))
    bot.process_new_updates([update])
    return "ok", 200


@celery.task
def download_and_process(remote_path, local_path, chat_id, question_number):
    """Download file from Telegram and process."""
    downloaded_file = bot.download_file(remote_path)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as new_file:
        new_file.write(downloaded_file)

    process_audio.delay(local_path, chat_id, question_number)


@celery.task
def process_audio(input_path, chat_id, question_number):
    """Process audio file."""
    output_path = os.path.join(
        "downloads", "compressed_" + f"{question_number}_" + os.path.basename(input_path) 
    )

    try:
        compressed_path = compress_audio(input_path, output_path)
        if compressed_path:
            transcription = transcribe_audio(compressed_path)
            if transcription:
                save_response(chat_id, f"question_{question_number}", transcription)
                next_question = question_number + 1
                if next_question < len(questions):
                    bot.send_message(chat_id, questions[next_question], parse_mode="Markdown")
                else:
                    bot.send_message(chat_id, "Thank you! All your responses have been recorded.")
            else:
                bot.send_message(chat_id, "Failed to transcribe audio.")
        else:
            bot.send_message(chat_id, "Failed to compress audio.")
    except Exception as e:
        print(f"Unexpected error: {e}")
    finally:
        if os.path.exists(input_path):
            os.remove(input_path)

        if not output_path.endswith(".mp3"):
            output_path = os.path.splitext(output_path)[0] + ".mp3"

        if os.path.exists(output_path):
            os.remove(output_path)


def compress_audio(input_path, output_path):
    """Compress audio file using ffmpeg."""
    try:
        if not output_path.endswith(".mp3"):
            output_path = os.path.splitext(output_path)[0] + ".mp3"

        probe = ffmpeg.probe(input_path)
        if not any(stream["codec_type"] == "audio" for stream in probe["streams"]):
            logger.error(f"No valid audio stream found in {input_path}")
            return None

        (
            ffmpeg.input(input_path)
            .output(
                output_path,
                ac=1,
                codec="libmp3lame",
                audio_bitrate="12k",
                application="voip",
            )
            .run(overwrite_output=True)
        )
        return output_path
    except Exception as e:
        logger.error(f"Error compressing audio: {e}")
        return None


def transcribe_audio(file_path):
    """Transcribe audio file using OpenAI's Whisper model."""
    try:
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        with open(file_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                model="whisper-1", file=f, language="en"
            )

        return transcription.text
    except Exception as e:
        logger.error(f"Error transcribing audio: {e}")
        return None


if __name__ == "__main__":
    app.run(host="0.0.0.0")
