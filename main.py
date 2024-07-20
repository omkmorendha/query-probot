import os
import openai
from flask import Flask, request
from telebot import TeleBot, types
import logging
from redis import Redis, ConnectionPool
import ast
import time
import json
import ffmpeg
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
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
pool = ConnectionPool.from_url(redis_url)

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

questions = [
    "What is your name?",
    "What is your state, city, and zip code?",
    "What is your preferred contact number?",
    "How many years of experience in the field of communication sciences (SLP/SLPA) do you have?",
    "In what settings have you worked?",
    "Do you have experience with infants and toddlers under 3?",
    "If you know any other languages, please share them.",
    "It is your first session with a little 2 year old.  You have done a full case review and you  see that he is not speaking but appears to understand.  Parents are VERY concerned.  They do not know you and have never met you before.  What is this first session in the  home looking like?  What do you do?",
    "This little one is not speaking.  Just pretend that you knew that he would only ever speak 5  words his whole life (we can't know this, but pretend) - and these 5 words were taught by  you at the age of 2.  What 5 words would you wish that you could teach him?",
    "This family knows and loves you now, but suppose they have an illness in the home - we  don't want you to go to a home if they are sick - and we will offer a virtual session.   How  are you keeping this little one engaged for a virtual 60 minute session?",
    "What is your current availability?",
    "What is your hourly pay rate?",
    "Do you have any questions for me? I will forward them to our team and get back to you after we  review your responses internally if the parameters are met.",
]


prompts = {
    7 : f"You are a point-scoring bot that strictly replies with 0, 5 or 10, \nThis is the question: {questions[7]} \n\nFollow the following points break down: Award 10 points for this best Answer:  Building  Rapport  - any mention of building rapport such as  playing with the child,  following child's lead in play/child-led play  , gaining trust, asking parents  about their concerns, addressing parent concerns, explaining what to expect, etc.  The key word  is rapport with how they plan to do that.  Award 5 Points for this  Acceptable Answer: Play (but no mention of child-led or following child's  lead)  Award 0 points Not acceptable:  Target goals right away.  Have parents wait outside. Anything  that is not building rapport or gaining trust.",
    8 : f"You are a point-scoring bot that strictly replies with 0, 5 or 10, \nThis is the question: {questions[8]} \n\nFollow the following points break down: Award 10 Points for this Best Answer:  Any list of 5  core/functional words  (e.g., help, want,  more, done/all done, yes, no, eat, drink, hurt, again, etc.)  Award 5 Points for this Acceptable Answers:  mom/dad/caregiver's name  Award 0 Points - Not Acceptable: colors, shapes, numbers, any word that is NOT functional and  would not allow for generalization to other tasks.  phone number, SSN - too old for a little child  who is 2-years-old to learn especially if they have no other words that they speak yet.",
    9 : f"You are a point-scoring bot that strictly replies with 0, 5 or 10, \nThis is the question: {questions[9]} \n\nFollow the following points break down: Award 10 points for this Best answers:  Any mention of the following:   Parent Coaching,  using  materials/toys in their home, letting parents know how to use the toys in the home to facilitate  language during play, communication temptations, songs on youtube, allowing the child to run  around and learn in the home, using actual toys that I have in my home, etc. -  must mention  family is actively involved in the session Award 5 points for this Acceptable answers: occasional computer games, boom cards, ultimate  SLP, etc.  Award 0 points for this Unacceptable answer(s):  Strapping the child into a high chair, parents  waiting in another room, no mention of parent coaching or the parents, lost look or I don't know.",
}


def get_score(question, transcription):
    """Generate a report based on the transcription using GPT-3.5."""

    if question not in prompts:
        return None

    try:
        openai_client = openai.OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
        )
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo-0125",
            messages=[
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": prompts[question]
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": transcription
                        }
                    ],
                },
            ],
            temperature=0,
        )
        report = response.choices[0].message.content

        try:
            score = int(report)

            if score in (0, 5, 10):
                return score
        except:
            pass

        return 0
    
    except Exception as e:
        logger.error(f"Error generating report: {e}")
        return None


@bot.message_handler(commands=["start", "restart"])
def start(message):
    """Handle /start and /restart commands."""
    chat_id = message.chat.id
    clear_responses(chat_id)

    message_to_send = "Welcome!\nI will send you questions for you to answer and your answers will then be sent to the appropriate team members!\nHold down the microphone to answer."
    bot.send_message(message.chat.id, message_to_send, parse_mode="Markdown")
    bot.send_message(message.chat.id, questions[0], parse_mode="Markdown")


def save_response(chat_id, key, value):
    redis_client = None
    try:
        redis_client = Redis(connection_pool=pool)
        responses = redis_client.hgetall(chat_id) or {}
        responses = {k.decode("utf-8"): v.decode("utf-8") for k, v in responses.items()}
        
        if isinstance(value, dict):
            value = json.dumps(value)
        elif not isinstance(value, (str, int, float)):
            value = str(value)

        responses[key] = value
        redis_client.hset(chat_id, mapping=responses)
    
    except Exception as e:
        print(f"Error in save_response {e}")
    
    finally:
        if redis_client:
            redis_client.close()


def clear_responses(chat_id):
    redis_client = Redis(connection_pool=pool)
    redis_client.delete(chat_id)
    redis_client.close()


def get_keyboard(question_number):
    keyboard = types.InlineKeyboardMarkup()

    if question_number == 3:  # Years of experience
        keyboard.add(
            types.InlineKeyboardButton("1+ years", callback_data="1+ years"),
            types.InlineKeyboardButton("Less than 1 year", callback_data="Less than 1 year")
        )
    elif question_number == 5:  # Experience with infants and toddlers
        keyboard.add(
            types.InlineKeyboardButton("Yes", callback_data="5_Yes"),
            types.InlineKeyboardButton("No", callback_data="5_No")
        )

    if question_number not in [0, len(questions)]:
        restart_button = types.InlineKeyboardButton("Restart", callback_data="restart")
        last_question_button = types.InlineKeyboardButton(
            "Answer Last Question Again", callback_data="last_question"
        )
        keyboard.add(restart_button, last_question_button)

    elif question_number >= (len(questions)):
        send_email_button = types.InlineKeyboardButton(
            "Send email", callback_data="send_email"
        )
        keyboard.add(send_email_button)

    return keyboard


def send_email(chat_id):
    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = int(os.environ.get("SMTP_PORT"))
    smtp_login = os.environ.get("SMTP_LOGIN")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    from_email = os.environ.get("FROM_EMAIL")
    to_emails = os.environ.get("TO_EMAIL").split(',')

    # Initialize Redis client
    redis_client = Redis(connection_pool=pool)
    try:
        responses = redis_client.hgetall(chat_id) or {}
    finally:
        redis_client.close()
    
    # Decode Redis responses
    responses = {k.decode("utf-8"): v.decode("utf-8") for k, v in responses.items()}
    
    if not responses:
        bot.send_message(chat_id, "No data recorded yet.")
        return

    total_score = 0
    message = "<h3>Recorded Data:</h3><br>"
    name = "Unknown"

    for i, question in enumerate(questions):
        response = responses.get(f"question_{i}")
        if response:
            response_dict = ast.literal_eval(response)
            answer = response_dict.get('text', 'N/A')
            remote_path = response_dict.get('remote_path', 'N/A')
            score = response_dict.get('score', None)

            if i == 0:
                name = answer
            
            new_message = f"<b>Question:</b> {question}<br><b>Answer:</b> {answer}"

            if remote_path != 'N/A':
                new_message += f"<br><b>Remote Path:</b> {remote_path}"

            if score is not None:
                total_score += score
                new_message += f"<br><b>Score:</b> {score}<br><br>"
            else:
                new_message += "<br><br>"

            message += new_message

    output = f"<h2>Total Score: {total_score}/50</h2><br>{message}"

    # Create the email
    msg = MIMEMultipart()
    msg['From'] = f"QueryPro Bot <{from_email}>"
    msg['To'] = ", ".join(to_emails)
    timestamp = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    msg['Subject'] = f"{name} {total_score} ({timestamp})"

    msg.attach(MIMEText(output, 'html'))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_login, smtp_password)
            server.sendmail(from_email, to_emails, msg.as_string())
            print("Email sent successfully")
    except Exception as e:
        print("Error sending email:", e)

    bot.send_message(chat_id, "Data sent successfully!")

@bot.message_handler(commands=["start", "restart"])
def start(message):

    """Handle /start and /restart commands."""
    chat_id = message.chat.id
    clear_responses(chat_id)
    message_to_send = "Welcome!\nI will send you questions for you to answer and your answers will then be sent to the appropriate team members!\nHold down the microphone to answer."
    bot.send_message(chat_id, message_to_send, parse_mode="Markdown")
    bot.send_message(chat_id, questions[0], parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    chat_id = call.message.chat.id
    
    if call.data == "restart":
        clear_responses(chat_id)
        start(call.message)
    elif call.data == "last_question":
        redis_client = Redis(connection_pool=pool)
        responses = redis_client.hgetall(chat_id) or {}
        redis_client.close
        responses = {k.decode("utf-8"): v.decode("utf-8") for k, v in responses.items()}

        current_question = len(responses)
        if current_question > 0:
            last_question_index = current_question - 1
            key_to_remove = f"question_{last_question_index}"
            redis_client = Redis(connection_pool=pool)
            redis_client.hdel(chat_id, key_to_remove)
            redis_client.close()

            bot.send_message(
                chat_id,
                questions[last_question_index],
                parse_mode="Markdown",
                reply_markup=get_keyboard(last_question_index),
            )
        else:
            bot.send_message(
                chat_id,
                "There is no previous question to answer.",
                reply_markup=get_keyboard(current_question),
            )
    elif call.data == "send_email":
        send_email(chat_id)
    elif call.data in ["1+ years", "Less than 1 year"]:
        current_question = 3
        score = 10 if call.data == "1+ years" else 0
        response = {
            "text": call.data,
            "score": score,
        }
        save_response(chat_id, f"question_{current_question}", response)
        next_question = current_question + 1
        bot.send_message(
            chat_id,
            questions[next_question],
            parse_mode="Markdown",
            reply_markup=get_keyboard(next_question),
        )
    elif call.data in ["5_Yes", "5_No"]:
        current_question = 5
        score = 10 if call.data == "5_Yes" else 0

        response = {
            "text": "Yes" if call.data == "5_Yes" else "No",
            "score": score,
        }
        save_response(chat_id, f"question_{current_question}", response)
        next_question = current_question + 1
        bot.send_message(
            chat_id,
            questions[next_question],
            parse_mode="Markdown",
            reply_markup=get_keyboard(next_question),
        )
    else:
        bot.answer_callback_query(call.id, "Invalid option")

    bot.answer_callback_query(call.id)



@bot.message_handler(content_types=["document", "audio", "voice", "text"])
def handle_responses(message):
    """Handle text and audio responses."""
    chat_id = message.chat.id
    redis_client = Redis(connection_pool=pool)
    responses = redis_client.hgetall(chat_id) or {}
    redis_client.close()

    if not responses:
        current_question = 0
    else:
        current_question = len(responses)

    if current_question < len(questions):
        if current_question == 2:
            bot.send_message(
                chat_id,
                "I will ask you a few questions and score your answers based on information provided by the team. Your answers and overall score will then be passed on to the team for follow up  at your preferred number or email address.  We use this method for fairness and everyone  is asked the same questions.  If your answers are within a certain score the team will  contact you.  You may also follow up at  hello@melospeech.com  . Any questions you have  can be added at the end of the process and will be forwarded to the team for follow up.",
                parse_mode="Markdown",
            )

        if current_question in [3, 5]:
            key_to_remove = f"question_{current_question}"
            redis_client = Redis(connection_pool=pool)
            redis_client.hdel(chat_id, key_to_remove)
            redis_client.close()

            bot.send_message(
                chat_id,
                "Please use the buttons to answer the question",
                parse_mode="Markdown",
            )

            bot.send_message(
                chat_id,
                questions[current_question],
                reply_markup=get_keyboard(current_question),
            )

        elif message.content_type == "text":
            text = message.text
            score = get_score(current_question, text)

            if score is not None:
                response = {
                    "text": message.text,
                    "score": score,
                }
            else:
                response = {
                    "text": message.text,
                }
            save_response(chat_id, f"question_{current_question}", response)

            next_question = current_question + 1

            if next_question < len(questions):
                bot.send_message(
                    chat_id,
                    questions[next_question],
                    parse_mode="Markdown",
                    reply_markup=get_keyboard(next_question),
                )
            else:
                bot.send_message(
                    chat_id,
                    "Thank you! All your responses have been recorded. Would you like to submit your application?",
                    reply_markup=get_keyboard(next_question),
                )

        elif message.content_type in ["audio", "voice"]:
            audio_file = message.audio or message.voice
            file_info = bot.get_file(audio_file.file_id)
            file_path = f"downloads/{audio_file.file_unique_id}.{file_info.file_path.split('.')[-1]}"
            bot.reply_to(message, "Please wait while we process the audio")
            download_and_process.delay(
                file_info.file_id, file_path, chat_id, current_question
            )
    else:
        bot.send_message(
            chat_id,
            "All questions have been answered. Thank you!",
            # reply_markup=get_keyboard(current_question),
        )


@app.route(f"/{WEBHOOK_SECRET}", methods=["POST"])
def webhook():
    """Webhook to handle incoming updates from Telegram."""
    update = types.Update.de_json(request.data.decode("utf8"))
    bot.process_new_updates([update])
    return "ok", 200


@celery.task
def download_and_process(file_id, local_path, chat_id, question_number):
    """Download file from Telegram and process."""
    file_info = bot.get_file(file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as new_file:
        new_file.write(downloaded_file)

    process_audio.delay(local_path, chat_id, question_number, file_id)


@celery.task
def process_audio(input_path, chat_id, question_number, file_id):
    """Process audio file."""
    output_path = os.path.join(
        "downloads",
        "compressed_" + f"{question_number}_" + os.path.basename(input_path),
    )

    try:
        compressed_path = compress_audio(input_path, output_path)
        if compressed_path:
            transcription = transcribe_audio(compressed_path)
            if transcription:
                score = get_score(question_number, transcription)
                
                file_info = bot.get_file(file_id)
                downloadable_link = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"

                if score is not None:
                    data = {
                        "text": transcription,
                        "remote_path": downloadable_link,
                        "score": score,
                    }
                else:
                    data = {
                        "text": transcription,
                        "remote_path": downloadable_link,
                    }

                save_response(chat_id, f"question_{question_number}", data)
                next_question = question_number + 1
                if next_question < len(questions):
                    bot.send_message(
                        chat_id,
                        questions[next_question],
                        parse_mode="Markdown",
                        reply_markup=get_keyboard(next_question),
                    )
                else:
                    bot.send_message(
                        chat_id,
                        "Thank you! All your responses have been recorded. Would you like to submit your application?",
                        reply_markup=get_keyboard(next_question),
                    )
            else:
                bot.send_message(
                    chat_id,
                    "Failed to transcribe audio.",
                    reply_markup=get_keyboard(question_number),
                )
        else:
            bot.send_message(
                chat_id,
                "Failed to compress audio.",
                reply_markup=get_keyboard(question_number),
            )
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
