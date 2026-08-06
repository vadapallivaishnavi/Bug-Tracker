"""
Alerting service: sends failure/event notifications to Gmail (via SMTP + Gmail App Password).

Both channels are best-effort: a failure to send an alert is logged but
never raised, so alerting code can never break the calling automation.
"""
import base64
import smtplib
import ssl
import logging
import yaml
import requests
from email.message import EmailMessage

logger = logging.getLogger(__name__)


class AlertService:
    def __init__(self, config_path='config.yaml'):
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        self.smtp_cfg = config.get('smtp', {})
        self.alert_cfg = config.get('alerts', {})

    def _enabled(self, channel):
        if not self.alert_cfg.get('enabled', False):
            return False
        return self.alert_cfg.get(channel, {}).get('enabled', False)

    def send_email(self, subject, body):
        if not self._enabled('email'):
            return False
        recipients = self.alert_cfg.get('email', {}).get('to', [])
        if not recipients:
            logger.warning("Email alert skipped: no recipients configured")
            return False

        host = self.smtp_cfg.get('host')
        port = int(self.smtp_cfg.get('port', 587))
        username = self.smtp_cfg.get('username')
        password = self.smtp_cfg.get('password')
        use_tls = self.smtp_cfg.get('use_tls', True)

        if not username or not password:
            logger.warning("Email alert skipped: SMTP username/app-password not configured")
            return False

        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = username
        msg['To'] = ", ".join(recipients)
        msg.set_content(body)

        try:
            if use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(host, port, timeout=10) as server:
                    server.starttls(context=context)
                    server.login(username, password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                    server.login(username, password)
                    server.send_message(msg)
            logger.info(f"Email alert sent to {recipients}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email alert: {e}")
            return False


    def notify(self, subject, message):
        """Fire both channels. Never raises."""
        try:
            self.send_email(subject, message)
        except Exception as e:
            logger.error(f"Unexpected error sending email alert: {e}")

    def send_custom_email(self, to_recipients, subject, body):
        """Send a one-off email to arbitrary recipients (e.g. a task-log summary),
        independent of the fixed alerting config/recipients. Returns (success, message).
        """
        recipients = [r.strip() for r in (to_recipients or []) if r and r.strip()]
        if not recipients:
            return False, "No recipients provided"

        host = self.smtp_cfg.get('host')
        port = int(self.smtp_cfg.get('port', 587))
        username = self.smtp_cfg.get('username')
        password = self.smtp_cfg.get('password')
        use_tls = self.smtp_cfg.get('use_tls', True)

        if not host or not username or not password:
            return False, "SMTP is not configured on the server"

        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = username
        msg['To'] = ", ".join(recipients)
        msg.set_content(body)

        try:
            if use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(host, port, timeout=10) as server:
                    server.starttls(context=context)
                    server.login(username, password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                    server.login(username, password)
                    server.send_message(msg)
            logger.info(f"Custom email sent to {recipients}")
            return True, "Email sent"
        except Exception as e:
            logger.error(f"Failed to send custom email: {e}")
            return False, str(e)

    def send_email_with_attachments(self, to_recipients, subject, body, attachments=None):
        """Send a one-off email with optional file attachments.

        attachments: list of {'filename': str, 'content_b64': str, 'mimetype': str}
        content_b64 is the raw base64 payload (no data: prefix). Returns (success, message).
        """
        recipients = [r.strip() for r in (to_recipients or []) if r and r.strip()]
        if not recipients:
            return False, "No recipients provided"

        host = self.smtp_cfg.get('host')
        port = int(self.smtp_cfg.get('port', 587))
        username = self.smtp_cfg.get('username')
        password = self.smtp_cfg.get('password')
        use_tls = self.smtp_cfg.get('use_tls', True)

        if not host or not username or not password:
            return False, "SMTP is not configured on the server"

        msg = EmailMessage()
        msg['Subject'] = subject
        msg['From'] = username
        msg['To'] = ", ".join(recipients)
        msg.set_content(body)

        for att in (attachments or []):
            try:
                filename = att.get('filename') or 'attachment'
                mimetype = att.get('mimetype') or 'application/octet-stream'
                maintype, _, subtype = mimetype.partition('/')
                if not subtype:
                    maintype, subtype = 'application', 'octet-stream'
                raw = base64.b64decode(att.get('content_b64') or '')
                msg.add_attachment(raw, maintype=maintype, subtype=subtype, filename=filename)
            except Exception as att_err:
                logger.warning(f"Skipping attachment '{att.get('filename')}': {att_err}")

        try:
            if use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(host, port, timeout=15) as server:
                    server.starttls(context=context)
                    server.login(username, password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                    server.login(username, password)
                    server.send_message(msg)
            logger.info(f"Custom email with attachments sent to {recipients}")
            return True, "Email sent"
        except Exception as e:
            logger.error(f"Failed to send custom email with attachments: {e}")
            return False, str(e)

