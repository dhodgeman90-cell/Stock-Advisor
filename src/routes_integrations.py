"""Integrations: bring-your-own Anthropic key (AI) and Gmail app password (email).

Secrets (the Anthropic key, the email app password) are write-only: they go to the
OS credential store and are NEVER returned in plaintext — the status endpoint reports
only set/not-set. Non-secret email routing fields live in integrations.yaml and ARE
returned so the user can see and edit them.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, HTTPException
from pydantic import BaseModel

from src import config, secrets_store, briefing
from src.deps import get_profile

logger = logging.getLogger(__name__)


class AiBody(BaseModel):
    api_key: str = ""           # "" clears the stored key


class EmailBody(BaseModel):
    user: str = ""
    to: str = ""
    host: str = "smtp.gmail.com"
    port: str = "465"
    password: Optional[str] = None   # None = leave existing; "" = clear; value = set


def register(app) -> None:
    @app.get("/api/integrations")
    def get_integrations(profile=Depends(get_profile)):
        ic = config.load_integrations(profile.config_dir)
        return {
            "ai": {"key_set": secrets_store.has_secret("ANTHROPIC_API_KEY")},
            "email": {
                "user": ic.get("EMAIL_USER", ""),
                "to": ic.get("EMAIL_TO", ""),
                "host": ic.get("EMAIL_HOST", "smtp.gmail.com"),
                "port": ic.get("EMAIL_PORT", "465"),
                "password_set": secrets_store.has_secret("EMAIL_PASSWORD"),
            },
        }

    @app.put("/api/integrations/ai")
    def put_ai(body: AiBody):
        key = (body.api_key or "").strip()
        if key:
            secrets_store.set_secret("ANTHROPIC_API_KEY", key)
        else:
            secrets_store.delete_secret("ANTHROPIC_API_KEY")
        return {"ok": True, "key_set": secrets_store.has_secret("ANTHROPIC_API_KEY")}

    @app.put("/api/integrations/email")
    def put_email(body: EmailBody, profile=Depends(get_profile)):
        port = (body.port or "").strip()
        if port and not port.isdigit():
            raise HTTPException(status_code=400, detail="SMTP port must be a number.")
        config.save_integrations(profile.config_dir, user=body.user, to=body.to,
                                 host=body.host, port=port)
        # Refresh the live profile so a run/test in this session uses the new config.
        profile.secrets.update_config_values(config.load_integrations(profile.config_dir))
        if body.password is not None:
            pw = body.password.strip()
            if pw:
                secrets_store.set_secret("EMAIL_PASSWORD", pw)
            else:
                secrets_store.delete_secret("EMAIL_PASSWORD")
        return {"ok": True, "password_set": secrets_store.has_secret("EMAIL_PASSWORD")}

    @app.post("/api/integrations/email/test")
    def test_email(profile=Depends(get_profile)):
        s = profile.secrets
        missing = [k for k in ("EMAIL_USER", "EMAIL_TO") if not s.get(k)]
        if not secrets_store.has_secret("EMAIL_PASSWORD"):
            missing.append("EMAIL_PASSWORD")
        if missing:
            raise HTTPException(status_code=400,
                                detail=f"Email not fully configured: missing {', '.join(missing)}")
        try:
            briefing.send_email(
                "Stock Advisor — test email",
                "This is a test email from Stock Advisor. Your email integration works.",
                host=s.get("EMAIL_HOST", "smtp.gmail.com"),
                port=int(s.get("EMAIL_PORT", "465")),
                user=s.get("EMAIL_USER"),
                password=s.get("EMAIL_PASSWORD"),
                to_addr=s.get("EMAIL_TO"),
            )
        except Exception as e:
            logger.warning("Test email send failed: %s", e)
            raise HTTPException(
                status_code=502,
                detail="Send failed — check your email address, SMTP host/port, and app password.",
            ) from e
        return {"ok": True}
