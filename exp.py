import os
from dotenv import load_dotenv
import datetime
import ast
from markdownmail import MarkdownMail

load_dotenv()
TO_EMAIL = ast.literal_eval(os.environ.get("TO_EMAIL"))

print("TO_EMAIL:", TO_EMAIL)
print("SMTP_SERVER:", os.environ.get("SMTP_SERVER"))
print("SMTP_PORT:", os.environ.get("SMTP_PORT"))
print("SMTP_LOGIN:", os.environ.get("SMTP_LOGIN"))
print("FROM_EMAIL:", os.environ.get("FROM_EMAIL"))

def send_email(chat_id):
    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = int(os.environ.get("SMTP_PORT"))
    smtp_login = os.environ.get("SMTP_LOGIN")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    from_email = os.environ.get("FROM_EMAIL")

    output = f"Total Score:"
    from_name = "QueryPro Bot"
    from_addr = f"{from_name} <{from_email}>"
    
    # Adding timestamp to the subject
    timestamp = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
    subject = f"({timestamp})"

    if TO_EMAIL:
        for to_email in TO_EMAIL:
            print("Sending to:", to_email)
            email = MarkdownMail(
                from_addr=from_addr, to_addr=to_email, subject=subject, content=output
            )
            try:
                email.send(
                    smtp_server, login=smtp_login, password=smtp_password, port=smtp_port
                )

                print("Email sent successfully to", to_email)
            except Exception as e:
                print("Error sending email to", to_email, ":", e)

        print(chat_id, "Data sent successfully!")
    else:
        print(chat_id, "No data recorded yet.")

send_email(1)
