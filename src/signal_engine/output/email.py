"""Send HTML email via Resend."""

from __future__ import annotations

import logging

import resend

from signal_engine.config import secret

log = logging.getLogger(__name__)


def send(subject: str, html: str, to: str | None = None) -> dict:
    resend.api_key = secret("RESEND_API_KEY")
    recipient = to or secret("USER_EMAIL")
    sender = secret("SENDER_EMAIL")
    response = resend.Emails.send(
        {
            "from": f"AI Signal Engine <{sender}>",
            "to": [recipient],
            "subject": subject,
            "html": html,
        }
    )
    log.info("Sent email id=%s to=%s", response.get("id"), recipient)
    return response


if __name__ == "__main__":
    from signal_engine.output.report import compose, record_sent

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    subject, html = compose()
    response = send(subject, html)
    record_sent(candidates_count=10)
    print(f"Sent: {response}")
