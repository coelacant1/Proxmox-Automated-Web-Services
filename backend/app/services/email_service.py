"""Email notification service - async SMTP with template rendering."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import aiosmtplib
from jinja2 import BaseLoader, Environment
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import SystemSetting

logger = logging.getLogger(__name__)

# SMTP setting keys stored in SystemSetting table
SMTP_SETTING_KEYS = {
    "smtp_enabled": "false",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_from_address": "paws@localhost",
    "smtp_from_name": "PAWS",
    "smtp_use_tls": "true",
}

_jinja_env = Environment(loader=BaseLoader(), autoescape=True)

# ---------------------------------------------------------------------------
# HTML email templates
# ---------------------------------------------------------------------------

_BASE_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#1a1a2e;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#1a1a2e;padding:24px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#16213e;border-radius:8px;overflow:hidden;">
  <tr><td style="background:#0f3460;padding:20px 24px;">
    <h1 style="margin:0;color:#e94560;font-size:20px;">PAWS</h1>
  </td></tr>
  <tr><td style="padding:24px;color:#e0e0e0;font-size:14px;line-height:1.6;">
    {{ content }}
  </td></tr>
  <tr><td style="padding:16px 24px;border-top:1px solid #1a1a2e;color:#888;font-size:12px;">
    Proxmox Automated Web Services
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""

TEMPLATES: dict[str, dict[str, str]] = {
    "welcome": {
        "subject": "Welcome to PAWS, {{ username }}!",
        "html": (
            "<h2 style='color:#e94560;margin-top:0;'>Welcome, {{ username }}!</h2>"
            "<p>Your account has been created successfully.</p>"
            "<p>You can now log in and start provisioning virtual machines, "
            "containers, and storage resources.</p>"
            "<p style='color:#888;'>If you did not create this account, please ignore this email.</p>"
        ),
        "text": "Welcome to PAWS, {{ username }}! Your account has been created.",
    },
    "quota_changed": {
        "subject": "PAWS - Your quota has been updated",
        "html": (
            "<h2 style='color:#e94560;margin-top:0;'>Quota Updated</h2>"
            "<p>Your resource quotas have been changed:</p>"
            "<ul>{% for change in changes %}"
            "<li><strong>{{ change.field }}</strong>: {{ change.old_value }} &rarr; {{ change.new_value }}</li>"
            "{% endfor %}</ul>"
        ),
        "text": "Your PAWS quotas have been updated.",
    },
    "resource_alert": {
        "subject": "PAWS - Resource Alert: {{ alert_type }}",
        "html": (
            "<h2 style='color:#e94560;margin-top:0;'>Resource Alert</h2>"
            "<p><strong>{{ alert_type }}</strong></p>"
            "<p>{{ message }}</p>"
            "{% if resource_name %}<p>Resource: <strong>{{ resource_name }}</strong></p>{% endif %}"
        ),
        "text": "PAWS Resource Alert: {{ alert_type }} - {{ message }}",
    },
    "backup_complete": {
        "subject": "PAWS - Backup {{ status }}",
        "html": (
            "<h2 style='color:#e94560;margin-top:0;'>Backup {{ status | capitalize }}</h2>"
            "<p>A backup operation for <strong>{{ resource_name }}</strong> has {{ status }}.</p>"
            "{% if details %}<p style='color:#888;'>{{ details }}</p>{% endif %}"
        ),
        "text": "PAWS Backup {{ status }} for {{ resource_name }}.",
    },
    "test": {
        "subject": "PAWS - Test Email",
        "html": (
            "<h2 style='color:#e94560;margin-top:0;'>Test Email</h2>"
            "<p>This is a test email from your PAWS installation.</p>"
            "<p>If you received this, your SMTP settings are configured correctly.</p>"
        ),
        "text": "PAWS test email. Your SMTP settings are working.",
    },
}


async def get_smtp_config(db: AsyncSession) -> dict[str, str]:
    """Load SMTP settings from the database, returning defaults for missing keys."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key.in_(SMTP_SETTING_KEYS.keys())))
    settings = {s.key: s.value for s in result.scalars().all()}
    return {k: settings.get(k, default) for k, default in SMTP_SETTING_KEYS.items()}


def render_template(template_name: str, context: dict[str, Any]) -> tuple[str, str, str]:
    """Render an email template, returning (subject, html_body, text_body)."""
    tmpl = TEMPLATES.get(template_name)
    if not tmpl:
        raise ValueError(f"Unknown email template: {template_name}")

    subject = _jinja_env.from_string(tmpl["subject"]).render(**context)
    inner_html = _jinja_env.from_string(tmpl["html"]).render(**context)
    html_body = _jinja_env.from_string(_BASE_TEMPLATE).render(content=inner_html)
    text_body = _jinja_env.from_string(tmpl["text"]).render(**context)
    return subject, html_body, text_body


async def send_email(
    to_address: str,
    subject: str,
    html_body: str,
    text_body: str,
    smtp_config: dict[str, str],
) -> bool:
    """Send an email via SMTP. Returns True on success, False on failure."""
    if smtp_config.get("smtp_enabled", "false").lower() != "true":
        logger.debug("SMTP disabled, skipping email to %s", to_address)
        return False

    host = smtp_config.get("smtp_host", "")
    if not host:
        logger.warning("SMTP host not configured, skipping email to %s", to_address)
        return False

    port = int(smtp_config.get("smtp_port", "587"))
    username = smtp_config.get("smtp_username", "")
    password = smtp_config.get("smtp_password", "")
    from_addr = smtp_config.get("smtp_from_address", "paws@localhost")
    from_name = smtp_config.get("smtp_from_name", "PAWS")
    use_tls = smtp_config.get("smtp_use_tls", "true").lower() == "true"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_address
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=host,
            port=port,
            username=username or None,
            password=password or None,
            start_tls=use_tls,
        )
        logger.info("Email sent to %s: %s", to_address, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_address)
        return False


async def send_template_email(
    db: AsyncSession,
    to_address: str,
    template_name: str,
    context: dict[str, Any] | None = None,
) -> bool:
    """Render a template and send the email."""
    ctx = context or {}
    subject, html_body, text_body = render_template(template_name, ctx)
    smtp_config = await get_smtp_config(db)
    return await send_email(to_address, subject, html_body, text_body, smtp_config)
