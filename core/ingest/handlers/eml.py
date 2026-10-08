"""
RFC-5322 / RFC-2822 Email (.eml) format handler (ADR-13).

Extracts sender, recipients, subject, date, thread genealogy (Message-ID, In-Reply-To, References),
and body text into structured, clean Sections. Strips redundant multi-level quoted email tails
to preserve token budget.
"""

from __future__ import annotations

import email
import email.policy
import re
from typing import List, Tuple

from ..base import FormatHandler, HandlerError, ParsedDocument, Section
from ..registry import register


@register
class EmailHandler(FormatHandler):
    name = "eml"
    version = "1"
    extensions = (".eml", ".msg")

    def parse(self, name: str, data: bytes) -> ParsedDocument:
        try:
            msg = email.message_from_bytes(data, policy=email.policy.default)
            subject = str(msg.get("Subject", "(No Subject)")).strip()
            from_hdr = str(msg.get("From", "Unknown Sender")).strip()
            to_hdr = str(msg.get("To", "")).strip()
            date_hdr = str(msg.get("Date", "")).strip()
            msg_id = str(msg.get("Message-ID", "")).strip().strip("<>")
            in_reply_to = str(msg.get("In-Reply-To", "")).strip().strip("<>")
            references = str(msg.get("References", "")).strip()

            title = subject if subject and subject != "(No Subject)" else self.title_from(name)
            doc = ParsedDocument(name=name, format=self.name, title=title)

            # 1. Header & Thread Metadata Section
            header_lines = [
                f"Subject: {subject}",
                f"From: {from_hdr}",
                f"To: {to_hdr}",
                f"Date: {date_hdr}",
            ]
            if msg_id:
                header_lines.append(f"Message-ID: <{msg_id}>")
            if in_reply_to:
                header_lines.append(f"In-Reply-To: <{in_reply_to}>")
            if references:
                header_lines.append(f"References: {references}")

            doc.sections.append(
                Section(path=("Headers",), text="\n".join(header_lines), locator="email:headers")
            )

            # 2. Extract Body (plain text preferred, fallback to HTML stripped)
            body_text = ""
            attachments: List[str] = []

            if msg.is_multipart():
                for part in msg.walk():
                    content_disposition = str(part.get("Content-Disposition", ""))
                    if "attachment" in content_disposition:
                        filename = part.get_filename() or "unnamed_attachment"
                        attachments.append(filename)
                        continue

                    ctype = part.get_content_type()
                    if ctype == "text/plain" and not body_text:
                        body_text = part.get_content()
                    elif ctype == "text/html" and not body_text:
                        # Strip basic HTML tags
                        raw_html = part.get_content()
                        body_text = re.sub(r"<[^>]+>", " ", raw_html)
                        body_text = re.sub(r"\s+", " ", body_text).strip()
            else:
                ctype = msg.get_content_type()
                if ctype == "text/plain":
                    body_text = msg.get_content()
                elif ctype == "text/html":
                    raw_html = msg.get_content()
                    body_text = re.sub(r"<[^>]+>", " ", raw_html)
                    body_text = re.sub(r"\s+", " ", body_text).strip()

            # Clean quoted tails (e.g. "> On Oct 8, ... wrote:")
            cleaned_body_lines: List[str] = []
            for line in (body_text or "").splitlines():
                stripped = line.strip()
                # Stop if deep quote block begins
                if stripped.startswith(">") or stripped.startswith("-----Original Message-----") or re.match(r"^On\s+.*wrote:$", stripped):
                    # We retain one level of reference or stop to avoid infinite quote chains
                    continue
                cleaned_body_lines.append(line)

            final_body = "\n".join(cleaned_body_lines).strip()
            if not final_body:
                final_body = body_text.strip() or "(Empty Message Body)"

            doc.sections.append(
                Section(path=("Message Body",), text=final_body, locator="email:body")
            )

            if attachments:
                doc.sections.append(
                    Section(
                        path=("Attachments",),
                        text="Attachments:\n" + "\n".join(f"- {a}" for a in attachments),
                        locator="email:attachments",
                    )
                )

            return doc
        except HandlerError:
            raise
        except Exception as exc:
            raise HandlerError(f"Failed to parse email: {exc}") from exc
