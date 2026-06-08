# ====================================================================
# JARVIS OMEGA — Social Reply Service
# ====================================================================
"""
Unified cross-platform DM reply system.
Uses Playwright browser automation to read and reply to messages on:
- Instagram (instagram.com)
- WhatsApp (web.whatsapp.com)
- Facebook Messenger (messenger.com)
- X / Twitter (x.com)

Requires the user to be logged in via the persistent Playwright profile.
The pw_browser service keeps a persistent Edge profile at ./storage/pw-profile
so login sessions survive restarts.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from shared.logger import get_logger

log = get_logger("social_reply")

# ---------------------------------------------------------------------------
# Platform Configurations
# ---------------------------------------------------------------------------

PLATFORMS = {
    "whatsapp": {
        "name": "WhatsApp",
        "url": "https://web.whatsapp.com",
        "dm_url": "https://web.whatsapp.com",
        "search_selector": 'div[contenteditable="true"][data-tab="3"]',
        "message_input_selector": 'div[contenteditable="true"][data-tab="10"]',
        "unread_js": """
            (() => {
                const chats = document.querySelectorAll('[data-testid="cell-frame-container"]');
                const unread = [];
                chats.forEach(chat => {
                    const badge = chat.querySelector('[data-testid="icon-unread-count"]') ||
                                  chat.querySelector('span[aria-label*="unread"]');
                    if (badge) {
                        const nameEl = chat.querySelector('span[dir="auto"][title]');
                        const name = nameEl ? nameEl.getAttribute('title') : 'Unknown';
                        const previewEl = chat.querySelector('span[dir="ltr"].quoted-mention, span.matched-text, span[dir="ltr"][class]');
                        const preview = previewEl ? previewEl.textContent : '';
                        unread.push({name, preview: preview.substring(0, 200)});
                    }
                });
                return JSON.stringify(unread.slice(0, 20));
            })()
        """,
    },
    "instagram": {
        "name": "Instagram",
        "url": "https://www.instagram.com/direct/inbox/",
        "dm_url": "https://www.instagram.com/direct/inbox/",
        "search_selector": 'input[placeholder="Search"]',
        "message_input_selector": 'textarea[placeholder="Message..."], div[contenteditable="true"][role="textbox"]',
        "unread_js": """
            (() => {
                const items = document.querySelectorAll('[role="listbox"] [role="option"], [class*="x1n2onr6"] a[href*="/direct/t/"]');
                const unread = [];
                items.forEach(item => {
                    const bold = item.querySelector('span[style*="font-weight: 600"], span[class*="x1lliihq"][class*="x1plvlek"]');
                    if (bold) {
                        const nameEl = item.querySelector('span[dir="auto"]');
                        const name = nameEl ? nameEl.textContent : 'Unknown';
                        const msgEl = item.querySelectorAll('span[dir="auto"]');
                        const preview = msgEl.length > 1 ? msgEl[msgEl.length - 1].textContent : '';
                        unread.push({name, preview: preview.substring(0, 200)});
                    }
                });
                return JSON.stringify(unread.slice(0, 20));
            })()
        """,
    },
    "messenger": {
        "name": "Messenger",
        "url": "https://www.messenger.com",
        "dm_url": "https://www.messenger.com",
        "search_selector": 'input[placeholder="Search Messenger"]',
        "message_input_selector": 'div[contenteditable="true"][role="textbox"]',
        "unread_js": """
            (() => {
                const rows = document.querySelectorAll('[role="row"], [data-testid="mwthreadlist-item"]');
                const unread = [];
                rows.forEach(row => {
                    const indicator = row.querySelector('[data-testid="badge"], [aria-label*="unread"]') ||
                                     row.querySelector('span[class*="x1lliihq"][style*="font-weight"]');
                    if (indicator) {
                        const spans = row.querySelectorAll('span');
                        const name = spans.length > 0 ? spans[0].textContent : 'Unknown';
                        const preview = spans.length > 1 ? spans[spans.length - 1].textContent : '';
                        unread.push({name, preview: preview.substring(0, 200)});
                    }
                });
                return JSON.stringify(unread.slice(0, 20));
            })()
        """,
    },
    "x": {
        "name": "X (Twitter)",
        "url": "https://x.com/messages",
        "dm_url": "https://x.com/messages",
        "search_selector": 'input[data-testid="SearchBox_Search_Input"]',
        "message_input_selector": 'div[data-testid="dmComposerTextInput"]',
        "unread_js": """
            (() => {
                const convos = document.querySelectorAll('[data-testid="conversation"]');
                const unread = [];
                convos.forEach(c => {
                    const indicator = c.querySelector('[data-testid="unread-indicator"], div[class*="r-sdzlij"]');
                    if (indicator) {
                        const nameEl = c.querySelector('span[class*="r-1vr29t4"]');
                        const name = nameEl ? nameEl.textContent : 'Unknown';
                        const msgEl = c.querySelector('span[class*="r-1b43r93"]');
                        const preview = msgEl ? msgEl.textContent : '';
                        unread.push({name, preview: preview.substring(0, 200)});
                    }
                });
                return JSON.stringify(unread.slice(0, 20));
            })()
        """,
    },
}

# Default Playwright browser API URL (pw_browser Flask server)
PW_API_BASE = "http://127.0.0.1:9223"


# ---------------------------------------------------------------------------
# Social Reply Service
# ---------------------------------------------------------------------------

class SocialReplyService:
    """
    Cross-platform DM reader and replier using Playwright browser automation.
    Talks to the pw_browser Flask API (runs on port 9223) which manages a
    persistent Chromium/Edge profile that preserves login sessions.
    """

    def __init__(self):
        self._last_scan: Dict[str, datetime] = {}
        self._cached_unread: Dict[str, List[Dict]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check_unread(self, platform: str) -> Dict[str, Any]:
        """
        Navigate to a platform's DM inbox and detect unread messages.

        Returns:
            {platform, unread_count, messages: [{name, preview}], logged_in}
        """
        pconf = PLATFORMS.get(platform)
        if not pconf:
            return {"error": f"Unknown platform: {platform}. Use: {list(PLATFORMS.keys())}"}

        log.info("checking_unread", platform=platform)

        # 1. Navigate to DM inbox
        nav_result = await self._pw_call("navigate", {"url": pconf["dm_url"]})
        if not nav_result.get("success"):
            return {"platform": platform, "error": "Navigation failed", "logged_in": False}

        await asyncio.sleep(3)  # Wait for page load

        # 2. Check if logged in
        info = await self._pw_call("info", {})
        if info.get("is_login_page"):
            return {
                "platform": platform,
                "logged_in": False,
                "error": f"Not logged in to {pconf['name']}. Please log in via the browser first.",
                "hint": f"Open {pconf['url']} in the Jarvis browser window and log in manually.",
            }

        # 3. Run unread detection JS
        try:
            js_result = await self._pw_call("js", {"script": pconf["unread_js"]})
            if js_result.get("success") and js_result.get("result"):
                raw = js_result["result"]
                # Handle both string and list returns
                if isinstance(raw, str):
                    try:
                        messages = json.loads(raw)
                    except json.JSONDecodeError:
                        messages = []
                else:
                    messages = raw if isinstance(raw, list) else []

                self._cached_unread[platform] = messages
                self._last_scan[platform] = datetime.utcnow()

                return {
                    "platform": platform,
                    "name": pconf["name"],
                    "logged_in": True,
                    "unread_count": len(messages),
                    "messages": messages,
                    "scanned_at": datetime.utcnow().isoformat(),
                }
        except Exception as e:
            log.error("unread_scan_failed", platform=platform, error=str(e))

        return {
            "platform": platform,
            "name": pconf["name"],
            "logged_in": True,
            "unread_count": 0,
            "messages": [],
            "scanned_at": datetime.utcnow().isoformat(),
        }

    async def check_all_platforms(self) -> Dict[str, Any]:
        """Scan all platforms for unread messages."""
        results = {}
        total_unread = 0
        for platform in PLATFORMS:
            result = await self.check_unread(platform)
            results[platform] = result
            total_unread += result.get("unread_count", 0)

        return {
            "total_unread": total_unread,
            "platforms": results,
            "scanned_at": datetime.utcnow().isoformat(),
        }

    async def open_chat(self, platform: str, contact_name: str) -> Dict[str, Any]:
        """
        Open a specific contact's chat on the given platform.
        Uses the search functionality to find and open the conversation.
        """
        pconf = PLATFORMS.get(platform)
        if not pconf:
            return {"error": f"Unknown platform: {platform}"}

        log.info("opening_chat", platform=platform, contact=contact_name)

        # Navigate to DM page
        await self._pw_call("navigate", {"url": pconf["dm_url"]})
        await asyncio.sleep(3)

        # Click search and type contact name
        search_sel = pconf.get("search_selector", "")
        if search_sel:
            try:
                await self._pw_call("click", {"selector": search_sel})
                await asyncio.sleep(0.5)
                await self._pw_call("type", {"selector": search_sel, "text": contact_name})
                await asyncio.sleep(2)  # Wait for search results
                # Press Enter or click the first result
                await self._pw_call("press", {"key": "Enter"})
                await asyncio.sleep(2)
            except Exception as e:
                log.error("search_failed", platform=platform, error=str(e))
                return {"success": False, "error": f"Could not search for {contact_name}: {e}"}

        return {
            "success": True,
            "platform": platform,
            "contact": contact_name,
            "message": f"Opened chat with {contact_name} on {pconf['name']}",
        }

    async def send_reply(
        self,
        platform: str,
        contact_name: str,
        message: str,
        polish: bool = True,
    ) -> Dict[str, Any]:
        """
        Open a contact's chat and send a message.

        Args:
            platform: whatsapp | instagram | messenger | x
            contact_name: Name of the person to message
            message: The message to send (raw from user)
            polish: If True, use LLM to polish the message first
        """
        pconf = PLATFORMS.get(platform)
        if not pconf:
            return {"error": f"Unknown platform: {platform}"}

        log.info("sending_reply", platform=platform, contact=contact_name, polish=polish)

        # 1. Polish the message via LLM if requested
        final_message = message
        if polish:
            try:
                from backend.services.llm_service import llm_service
                refined = await llm_service.get_response(
                    user_message=f"Polish this message to {contact_name}: {message}",
                    system_instructions=(
                        "You are JARVIS polishing a message on Sir's behalf. "
                        "Make it natural and human-sounding. Keep the same meaning and tone. "
                        "Output ONLY the polished message, nothing else."
                    ),
                    inject_memory=False,
                )
                final_message = refined.strip()
            except Exception as e:
                log.warning("polish_failed_using_raw", error=str(e))

        # 2. Open the chat
        open_result = await self.open_chat(platform, contact_name)
        if not open_result.get("success"):
            return {
                "success": False,
                "platform": platform,
                "contact": contact_name,
                "error": open_result.get("error", "Failed to open chat"),
                "drafted_message": final_message,
            }

        # 3. Type and send the message
        input_sel = pconf.get("message_input_selector", "")
        try:
            if input_sel:
                await self._pw_call("click", {"selector": input_sel})
                await asyncio.sleep(0.5)
            await self._pw_call("type", {"selector": input_sel or ":focus", "text": final_message})
            await asyncio.sleep(0.5)
            await self._pw_call("press", {"key": "Enter"})
            await asyncio.sleep(1)
        except Exception as e:
            return {
                "success": False,
                "platform": platform,
                "contact": contact_name,
                "error": f"Failed to type/send message: {e}",
                "drafted_message": final_message,
            }

        log.info("reply_sent", platform=platform, contact=contact_name, msg_len=len(final_message))

        return {
            "success": True,
            "platform": platform,
            "contact": contact_name,
            "message_sent": final_message,
            "original_message": message if polish else None,
            "polished": polish,
            "sent_at": datetime.utcnow().isoformat(),
        }

    async def draft_reply(self, contact_name: str, message: str, context: str = "") -> Dict[str, Any]:
        """
        Use LLM to draft a polished reply without sending it.
        Returns the drafted message for user review.
        """
        from backend.services.llm_service import llm_service

        system_prompt = (
            "You are JARVIS composing a message on Sir's behalf. "
            "Sir wants to reply to someone. Take his rough intent and turn it into a "
            "polished, natural message that sounds like it was written by him — not by an AI. "
            "Keep his tone, just refine it. Output ONLY the refined message, nothing else."
        )

        user_msg = f"Sir wants to reply to {contact_name}: {message}"
        if context:
            user_msg += f"\n\nContext of their conversation: {context}"

        try:
            refined = await llm_service.get_response(
                user_message=user_msg,
                system_instructions=system_prompt,
                inject_memory=False,
            )
            return {
                "success": True,
                "contact": contact_name,
                "original": message,
                "drafted": refined.strip(),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def read_latest_messages(self, platform: str, contact_name: str, count: int = 10) -> Dict[str, Any]:
        """
        Open a contact's chat and read the latest messages.
        Uses JavaScript to extract visible message text.
        """
        pconf = PLATFORMS.get(platform)
        if not pconf:
            return {"error": f"Unknown platform: {platform}"}

        # Open the chat first
        await self.open_chat(platform, contact_name)
        await asyncio.sleep(2)

        # Platform-specific JS to extract messages
        extract_js = """
            (() => {
                const msgs = [];
                const els = document.querySelectorAll(
                    '[data-testid="msg-container"], ' +
                    '[class*="message"], ' +
                    '[role="row"] [dir="auto"], ' +
                    'div[data-pre-plain-text]'
                );
                els.forEach(el => {
                    const text = el.textContent || el.innerText || '';
                    if (text.trim().length > 0 && text.trim().length < 1000) {
                        msgs.push(text.trim().substring(0, 300));
                    }
                });
                return JSON.stringify(msgs.slice(-""" + str(count) + """));
            })()
        """

        try:
            result = await self._pw_call("js", {"script": extract_js})
            if result.get("success") and result.get("result"):
                messages = json.loads(result["result"]) if isinstance(result["result"], str) else result["result"]
                return {
                    "success": True,
                    "platform": platform,
                    "contact": contact_name,
                    "messages": messages,
                    "count": len(messages),
                }
        except Exception as e:
            log.error("read_messages_failed", platform=platform, error=str(e))

        return {"success": False, "platform": platform, "contact": contact_name, "messages": [], "count": 0}

    async def auto_reply_all(self, platform: str, style: str = "polite") -> Dict[str, Any]:
        """
        Scan unread messages on a platform and auto-reply to all of them.
        Uses LLM to generate contextual replies based on the message preview.
        """
        scan = await self.check_unread(platform)
        if not scan.get("logged_in"):
            return scan

        messages = scan.get("messages", [])
        if not messages:
            return {"platform": platform, "auto_replied": 0, "message": "No unread messages"}

        from backend.services.llm_service import llm_service

        results = []
        for msg in messages:
            contact = msg.get("name", "Unknown")
            preview = msg.get("preview", "")

            if not preview:
                continue

            # Generate contextual reply
            try:
                reply_text = await llm_service.get_response(
                    user_message=f"Someone named {contact} sent me this on {platform}: \"{preview}\"",
                    system_instructions=(
                        f"You are JARVIS. Sir wants you to auto-reply to this message in a {style} tone. "
                        "Compose a brief, natural reply as if Sir wrote it himself. "
                        "Output ONLY the reply text, nothing else."
                    ),
                    inject_memory=True,
                )

                send_result = await self.send_reply(
                    platform=platform,
                    contact_name=contact,
                    message=reply_text.strip(),
                    polish=False,  # Already LLM-generated
                )
                results.append({
                    "contact": contact,
                    "their_message": preview,
                    "our_reply": reply_text.strip(),
                    "sent": send_result.get("success", False),
                })
            except Exception as e:
                results.append({"contact": contact, "error": str(e), "sent": False})

        return {
            "platform": platform,
            "auto_replied": sum(1 for r in results if r.get("sent")),
            "total_unread": len(messages),
            "results": results,
        }

    def get_supported_platforms(self) -> List[Dict[str, str]]:
        """List all supported social platforms."""
        return [
            {"key": k, "name": v["name"], "url": v["url"]}
            for k, v in PLATFORMS.items()
        ]

    # ------------------------------------------------------------------
    # Playwright API helper
    # ------------------------------------------------------------------

    async def _pw_call(self, endpoint: str, data: dict, timeout: float = 30.0) -> dict:
        """Call the pw_browser Flask API."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                if endpoint in ("info", "screenshot"):
                    resp = await client.post(f"{PW_API_BASE}/{endpoint}")
                else:
                    resp = await client.post(f"{PW_API_BASE}/{endpoint}", json=data)
                return resp.json()
        except httpx.ConnectError:
            return {
                "success": False,
                "error": "Browser service not running. Start it with: python backend/services/pw_browser.py",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}


# Singleton
social_reply_service = SocialReplyService()
