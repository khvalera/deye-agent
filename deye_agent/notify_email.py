
import smtplib
from email.message import EmailMessage
from .i18n import _

def send_email(config, subject, body, debug=False):
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = config.get("NOTIFY_EMAIL_FROM")
        msg["To"] = config.get("NOTIFY_EMAIL_TO")
        msg.set_content(body)

        smtp_server = config.get("NOTIFY_EMAIL_SMTP_SERVER")
        smtp_port = int(config.get("NOTIFY_EMAIL_SMTP_PORT", 587))
        smtp_user = config.get("NOTIFY_EMAIL_SMTP_USER")
        smtp_pass = config.get("NOTIFY_EMAIL_SMTP_PASSWORD")

        if debug:
            print(_("Preparing SMTP connection to {}:{}").format(smtp_server, smtp_port))

        # --- AUTO SELECT SSL OR STARTTLS ---
        if smtp_port == 465:
            # SSL MODE
            if debug:
                print(_("Using SMTP_SSL (implicit SSL)"))
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10)

        else:
            # STARTTLS MODE
            if debug:
                print(_("Using SMTP with STARTTLS"))
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
            server.set_debuglevel(1 if debug else 0)

            # Only start TLS when supported
            try:
                server.starttls()
                if debug:
                    print(_("TLS encryption established"))
            except Exception as e:
                print(_("Warning: STARTTLS failed:"), e)

        # --- LOGIN IF CREDENTIALS PROVIDED ---
        if smtp_user and smtp_pass:
            if debug:
                print(_("Logging in as {}").format(smtp_user))
            server.login(smtp_user, smtp_pass)
        else:
            if debug:
                print(_("No SMTP authentication used"))

        # --- SEND E-MAIL ---
        if debug:
            print(_("Sending email to {}").format(msg["To"]))

        server.send_message(msg)
        server.quit()

        if debug:
            print(_("Notification email successfully sent to {}").format(msg["To"]))

    except Exception as e:
        print(_("Error sending notification email:"), e)
