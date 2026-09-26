#!/usr/bin/env python3
"""
Agentic Action Dispatcher for Aegis Sovereign Knowledge Appliance.
Monitors classified documents, detects time-sensitive events (bills due soon,
overdue payments, high-value transfers, and legal notices), and routes actionable alerts.

Invariants:
- Zero Plaintext Secrets.
- Local CPU execution.
- Deterministic deduplication to prevent alert spamming.
- Configurable notification channels via environment variables.
"""

import datetime
import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..graph.extractor import extract_monetary_amounts

logger = logging.getLogger("sovereign_action_dispatcher")

DEFAULT_STATE_FILE = Path(os.getenv("SOVEREIGN_ACTION_STATE_FILE", "data/rag/action_dispatcher_state.json"))
TELEGRAM_BOT_TOKEN = os.getenv("SOVEREIGN_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("SOVEREIGN_TELEGRAM_CHAT_ID", "")
ALERT_WEBHOOK_URL = os.getenv("SOVEREIGN_ALERT_WEBHOOK_URL", "")


def extract_due_dates(text: str) -> List[datetime.date]:
    """
    Extracts due dates (data de vencimento) from document text.
    Matches Brazilian (DD/MM/YYYY) and ISO (YYYY-MM-DD) formats.
    """
    pattern = re.compile(
        r'(?:data\s+de\s+vencimento|vencimento(?:\s+em)?|vence(?:\s+em)?|pagar\s+at[eé]|venc\.?)\s*:?\s*(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})',
        re.IGNORECASE
    )
    due_dates: List[datetime.date] = []

    for match in pattern.finditer(text):
        raw = match.group(1).strip()
        parsed: Optional[datetime.date] = None
        if "/" in raw:
            parts = raw.split("/")
            try:
                parsed = datetime.date(int(parts[2]), int(parts[1]), int(parts[0]))
            except (ValueError, IndexError):
                pass
        elif "-" in raw:
            parts = raw.split("-")
            try:
                parsed = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
            except (ValueError, IndexError):
                pass

        if parsed and parsed not in due_dates:
            due_dates.append(parsed)

    return due_dates


def extract_max_monetary_amount(text: str) -> Optional[float]:
    """Extracts highest monetary value in Brazilian Reais from text."""
    amounts = extract_monetary_amounts(text)
    if not amounts:
        return None
    values = [a.metadata.get("value", 0.0) for a in amounts if isinstance(a.metadata.get("value"), (int, float))]
    return max(values) if values else None


@dataclass
class DocumentAction:
    doc_id: int
    action_type: str  # "BILL_DUE_SOON", "OVERDUE_BILL", "HIGH_VALUE_PAYMENT", "CRITICAL_NOTICE"
    severity: str     # "CRITICAL", "WARNING", "INFO"
    title: str
    message: str
    amount: Optional[float] = None
    due_date: Optional[str] = None
    correspondent: Optional[str] = None
    suggested_channels: List[str] = field(default_factory=lambda: ["webhook", "telegram"])
    created_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "action_type": self.action_type,
            "severity": self.severity,
            "title": self.title,
            "message": self.message,
            "amount": self.amount,
            "due_date": self.due_date,
            "correspondent": self.correspondent,
            "suggested_channels": self.suggested_channels,
            "created_at": self.created_at,
        }


class ActionEvaluator:
    """Evaluates business rules against document metadata and text to trigger actions."""
    def __init__(self, current_date: Optional[datetime.date] = None):
        self.current_date = current_date or datetime.date.today()

    def evaluate_document(self, doc: Dict[str, Any]) -> List[DocumentAction]:
        doc_id = int(doc["id"])
        title = doc.get("title") or ""
        content = doc.get("content") or ""
        correspondent = doc.get("correspondent") or ""

        combined = f"{title}\n{content}"
        actions: List[DocumentAction] = []

        max_amount = extract_max_monetary_amount(combined)
        due_dates = extract_due_dates(combined)

        # 1. Due Date Rules
        for due in due_dates:
            delta = (due - self.current_date).days
            due_str = due.strftime("%d/%m/%Y")

            if delta < 0 and delta >= -14:
                actions.append(DocumentAction(
                    doc_id=doc_id,
                    action_type="OVERDUE_BILL",
                    severity="CRITICAL",
                    title=title,
                    message=f"Overdue payment: {title} was due on {due_str} ({abs(delta)} days ago).",
                    amount=max_amount,
                    due_date=due.isoformat(),
                    correspondent=correspondent,
                    suggested_channels=["webhook", "telegram"]
                ))
            elif 0 <= delta <= 3:
                actions.append(DocumentAction(
                    doc_id=doc_id,
                    action_type="BILL_DUE_SOON",
                    severity="WARNING",
                    title=title,
                    message=f"Bill due soon: {title} is due in {delta} days ({due_str}).",
                    amount=max_amount,
                    due_date=due.isoformat(),
                    correspondent=correspondent,
                    suggested_channels=["webhook", "telegram"]
                ))

        # 2. High Value Rule (> R$ 1,000.00)
        if max_amount is not None and max_amount >= 1000.0:
            actions.append(DocumentAction(
                doc_id=doc_id,
                action_type="HIGH_VALUE_PAYMENT",
                severity="WARNING",
                title=title,
                message=f"High-value document detected: {title} (R$ {max_amount:,.2f}).",
                amount=max_amount,
                correspondent=correspondent,
                suggested_channels=["webhook", "telegram"]
            ))

        # 3. Critical Notices
        norm_combined = combined.lower()
        if "intimacao" in norm_combined or "intimação" in norm_combined or "notificacao judicial" in norm_combined:
            actions.append(DocumentAction(
                doc_id=doc_id,
                action_type="CRITICAL_NOTICE",
                severity="CRITICAL",
                title=title,
                message=f"Urgent legal notice detected: {title}.",
                correspondent=correspondent,
                suggested_channels=["webhook", "telegram"]
            ))

        return actions


class ActionDispatcher:
    """Dispatches alerts via Webhook or Telegram with persistent deduplication."""
    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file or DEFAULT_STATE_FILE
        self.state: Dict[str, Any] = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"dispatched_actions": {}, "history": []}

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def _make_action_key(self, action: DocumentAction) -> str:
        amount_part = f"{action.amount:.2f}" if action.amount else "na"
        due_part = action.due_date or "na"
        return f"{action.doc_id}:{action.action_type}:{amount_part}:{due_part}"

    def _send_webhook(self, action: DocumentAction) -> bool:
        """Sends JSON alert payload to configured webhook URL."""
        if not ALERT_WEBHOOK_URL:
            return False

        payload = json.dumps(action.to_dict()).encode("utf-8")
        req = urllib.request.Request(
            ALERT_WEBHOOK_URL,
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status in (200, 201, 202, 204)
        except Exception as e:
            logger.warning(f"Webhook dispatch failed: {e}")
            return False

    def _send_telegram(self, action: DocumentAction) -> bool:
        """Sends formatted HTML alert to Telegram if token and chat ID are set."""
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return False

        severity_emoji = "🚨" if action.severity == "CRITICAL" else "⚠️"
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

        lines = [
            f"{severity_emoji} <b>Sovereign Alert: {action.action_type.replace('_', ' ').title()}</b>",
            f"<b>Document:</b> {action.title}",
        ]
        if action.correspondent:
            lines.append(f"<b>Correspondent:</b> {action.correspondent}")
        if action.amount:
            lines.append(f"<b>Amount:</b> R$ {action.amount:,.2f}")
        if action.due_date:
            lines.append(f"<b>Due Date:</b> {action.due_date}")
        lines.append(f"<b>Details:</b> {action.message}")

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": "\n".join(lines),
            "parse_mode": "HTML"
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"Telegram dispatch failed: {e}")
            return False

    def dispatch(self, actions: List[DocumentAction]) -> List[Dict[str, Any]]:
        """Processes and dispatches candidate actions, skipping already alerted items."""
        results = []
        now_iso = datetime.datetime.now().isoformat()

        for action in actions:
            key = self._make_action_key(action)
            if key in self.state["dispatched_actions"]:
                continue

            delivered = False
            # 1. Webhook
            if ALERT_WEBHOOK_URL:
                if self._send_webhook(action):
                    delivered = True

            # 2. Telegram
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                if self._send_telegram(action):
                    delivered = True

            # If no channel configured, still record state for local UI
            if not ALERT_WEBHOOK_URL and not (TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID):
                delivered = True

            self.state["dispatched_actions"][key] = {
                "dispatched_at": now_iso,
                "action": action.to_dict(),
                "delivered": delivered,
            }
            self.state["history"].append({
                "key": key,
                "dispatched_at": now_iso,
                "delivered": delivered,
                "severity": action.severity,
                "title": action.title
            })
            results.append({"key": key, "action": action.to_dict(), "delivered": delivered})

        if results:
            self._save_state()

        return results
