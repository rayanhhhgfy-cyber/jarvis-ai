from __future__ import annotations

import asyncio
import io
import os
from typing import Optional, Dict, Any

from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from backend.config import settings
from backend.vault.secure_vault import secure_vault
from shared.logger import get_logger

log = get_logger("telegram_bridge")

COMMANDS = {
    "start": "Start the bot and get help",
    "screen": "Capture and send a screenshot",
    "status": "Get system vitals (CPU/RAM/Disk)",
    "task": "Execute a command (e.g. /task open chrome)",
    "focus": "Control Focus Mode (e.g. /focus Studying 60, /focus off)",
    "reply": "Reply on your behalf (e.g. /reply John Hey, I'll be there at 5)",
    "research": "Run a parallel web Research Swarm (e.g. /research best Python frameworks 2025)",
    "help": "Show this help message",
}


class TelegramBridge:
    """
    Telegram bot for remote device access.
    Allows Sir to send commands, view screenshots, and monitor vitals from mobile.
    """

    def __init__(self) -> None:
        self._app: Optional[Application] = None
        self._bot: Optional[Bot] = None
        self._allowed_user_id: Optional[int] = None
        self._running = False
        self._telegram_chats: Dict[str, int] = {}

    async def start(self) -> None:
        bot_token = secure_vault.retrieve("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            log.warning("telegram_missing_token_skipping")
            return

        self._app = Application.builder().token(bot_token).build()
        self._bot = self._app.bot

        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("screen", self._cmd_screen))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("task", self._cmd_task))
        self._app.add_handler(CommandHandler("focus", self._cmd_focus))
        self._app.add_handler(CommandHandler("reply", self._cmd_reply))
        self._app.add_handler(CommandHandler("research", self._cmd_research))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))

        await self._app.initialize()
        await self._app.start()
        self._running = True
        log.info("telegram_bridge_started")

    async def stop(self) -> None:
        if self._app:
            await self._app.stop()
            await self._app.shutdown()
        self._running = False
        log.info("telegram_bridge_stopped")

    def _record_chat(self, update: Update) -> None:
        """Record mapping of user names/usernames to chat IDs for replying."""
        if not update or not update.effective_user or not update.effective_chat:
            return
        user = update.effective_user
        chat = update.effective_chat
        if user.first_name:
            self._telegram_chats[user.first_name.lower()] = chat.id
        if user.last_name:
            self._telegram_chats[user.last_name.lower()] = chat.id
            if user.first_name:
                self._telegram_chats[f"{user.first_name.lower()} {user.last_name.lower()}"] = chat.id
        if user.username:
            self._telegram_chats[user.username.lower()] = chat.id
            self._telegram_chats[f"@{user.username.lower()}"] = chat.id

    def _authorize(self, update: Update) -> bool:
        self._record_chat(update)
        user_id = update.effective_user.id if update.effective_user else None
        if self._allowed_user_id and user_id != self._allowed_user_id:
            return False
        if self._allowed_user_id is None and user_id:
            self._allowed_user_id = user_id
        return True

    async def _cmd_start(self, update: Update, context) -> None:
        if not self._authorize(update):
            return
        await update.message.reply_text(
            f"J.A.R.V.I.S. OMEGA — Remote Link Active\n\n"
            f"Sir, I am online and ready.\n"
            f"Use /help to see available commands."
        )

    async def _cmd_help(self, update: Update, context) -> None:
        if not self._authorize(update):
            return
        help_text = "\n".join(f"/{cmd} — {desc}" for cmd, desc in COMMANDS.items())
        await update.message.reply_text(f"Available commands:\n\n{help_text}")

    async def _cmd_screen(self, update: Update, context) -> None:
        if not self._authorize(update):
            return
        await update.message.reply_text("Capturing screen, Sir...")
        try:
            from local_client.screenshot_manager import screenshot_manager
            img_bytes = screenshot_manager.capture()
            await update.message.reply_photo(photo=io.BytesIO(img_bytes))
        except Exception as e:
            await update.message.reply_text(f"Failed to capture screen: {e}")

    async def _cmd_status(self, update: Update, context) -> None:
        if not self._authorize(update):
            return
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            msg = (
                f"System Status:\n"
                f"CPU: {cpu}%\n"
                f"RAM: {mem.percent}% ({mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB)\n"
                f"DISK: {disk.percent}% ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)"
            )
            await update.message.reply_text(msg)
        except Exception as e:
            await update.message.reply_text(f"Status check failed: {e}")

    async def _cmd_task(self, update: Update, context) -> None:
        if not self._authorize(update):
            return
        cmd = " ".join(context.args)
        if not cmd:
            await update.message.reply_text("Usage: /task <command>\nExample: /task open chrome")
            return
        await update.message.reply_text(f"Executing: {cmd}")
        try:
            from backend.services.command_interpreter import command_interpreter
            import subprocess
            commands = command_interpreter.interpret(cmd)
            if commands:
                results = []
                for desc, shell_cmd in commands:
                    proc = subprocess.run(shell_cmd, shell=True, capture_output=True, text=True, timeout=15)
                    output = proc.stdout[:500] if proc.stdout else (proc.stderr[:500] if proc.stderr else "Done.")
                    results.append(f"{desc}: {output}")
                await update.message.reply_text("\n\n".join(results))
            else:
                await update.message.reply_text("No matching command found for that request.")
        except Exception as e:
            await update.message.reply_text(f"Execution failed: {e}")

    async def _cmd_focus(self, update: Update, context) -> None:
        if not self._authorize(update):
            return
        
        args = context.args
        from backend.services.focus_mode import focus_mode_service

        if not args:
            status = focus_mode_service.get_status()
            if status["active"]:
                rem = ""
                if status["time_remaining_seconds"]:
                    rem = f" ({int(status['time_remaining_seconds'] // 60)}m remaining)"
                await update.message.reply_text(
                    f"Sir, Focus Mode is currently active: '{status['focus_note']}'{rem}.\n"
                    f"To turn it off, use: /focus off"
                )
            else:
                await update.message.reply_text(
                    "Sir, Focus Mode is currently inactive.\n"
                    "Usage: /focus <note> [duration_minutes]\n"
                    "Example: /focus Working on project 60"
                )
            return

        action = args[0].lower()
        if action in ("off", "deactivate", "stop"):
            res = focus_mode_service.deactivate()
            if res.get("queued_count", 0) > 0:
                await update.message.reply_text("Focus Mode deactivated, Sir. Let me summarize your missed notifications...")
                summary = await focus_mode_service.generate_queued_summary()
                await update.message.reply_text(f"Sir, here is the summary of what you missed:\n\n{summary}")
            else:
                await update.message.reply_text("Focus Mode deactivated, Sir. You did not miss any messages.")
            return

        # Activate Focus Mode
        duration = None
        note_words = list(args)
        if len(args) > 1 and args[-1].isdigit():
            duration = int(args[-1])
            note_words = args[:-1]

        note = " ".join(note_words)
        focus_mode_service.activate(note, duration_minutes=duration)
        
        duration_msg = f" for {duration} minutes" if duration else ""
        await update.message.reply_text(f"Focus Mode activated, Sir: '{note}'{duration_msg}.")

    async def _cmd_reply(self, update: Update, context) -> None:
        """Compose and send a polished reply on behalf of Sir."""
        if not self._authorize(update):
            return
        
        import shlex
        args_str = " ".join(context.args) if context.args else ""
        if not args_str:
            await update.message.reply_text(
                "Usage: /reply [platform] <contact_name> <message>\n"
                "Platforms: whatsapp, instagram, messenger, x, telegram\n"
                "Example: /reply whatsapp John Hey, I'll be late\n"
                "Or: /reply John Hey, I'll be late (auto-detects platform)"
            )
            return

        try:
            try:
                parts = shlex.split(args_str)
            except Exception:
                parts = args_str.split()

            if len(parts) < 2:
                await update.message.reply_text(
                    "Usage: /reply [platform] <contact_name> <message>\n"
                    "Please provide both a contact name and a message."
                )
                return

            first_arg = parts[0].lower()
            supported_platforms = ["whatsapp", "instagram", "messenger", "x", "telegram", "discord"]
            
            if first_arg in supported_platforms:
                platform = first_arg
                contact_name = parts[1]
                message = " ".join(parts[2:])
            else:
                contact_name = parts[0]
                message = " ".join(parts[1:])
                # Auto-detect platform
                platform = None
                contact_lower = contact_name.lower().lstrip('@')
                
                # Check telegram chats
                if contact_lower in self._telegram_chats or f"@{contact_lower}" in self._telegram_chats:
                    platform = "telegram"
                else:
                    # Check social_reply_service unread
                    try:
                        from backend.services.social_reply_service import social_reply_service
                        for p, msgs in social_reply_service._cached_unread.items():
                            for m in msgs:
                                name = m.get("name", "").lower()
                                if contact_lower == name or contact_lower in name:
                                    platform = p
                                    break
                            if platform:
                                break
                    except Exception:
                        pass
                
                if not platform:
                    platform = "whatsapp"  # default fallback

            await update.message.reply_text(
                f"Processing reply on platform **{platform}** for **{contact_name}**..."
            )

            # Route to platform
            if platform == "telegram":
                contact_key = contact_name.lower().lstrip('@')
                chat_id = self._telegram_chats.get(contact_key) or self._telegram_chats.get(f"@{contact_key}")
                if not chat_id:
                    await update.message.reply_text(
                        f"❌ Could not find a Telegram chat ID for contact '{contact_name}'.\n"
                        f"Make sure they have texted the bot first so I have their chat ID."
                    )
                    return

                # Polish message
                from backend.services.llm_service import llm_service
                system_prompt = (
                    "You are JARVIS composing a message on Sir's behalf. "
                    "Sir wants to reply to someone. Take his rough intent and turn it into a "
                    "polished, natural message that sounds like it was written by him — not by an AI. "
                    "Keep his tone, just refine it. Output ONLY the refined message, nothing else."
                )
                refined = await llm_service.get_response(
                    user_message=f"Sir wants to reply to {contact_name}: {message}",
                    system_instructions=system_prompt,
                    inject_memory=False,
                )
                final_message = refined.strip()

                await self._bot.send_message(chat_id=chat_id, text=final_message)
                await update.message.reply_text(
                    f"✅ Message sent to {contact_name} on Telegram:\n\n{final_message}"
                )

            elif platform == "discord":
                from backend.discord.discord_bridge import discord_bridge
                contact_key = contact_name.lower().lstrip('@')
                user = None
                if hasattr(discord_bridge, "_discord_users"):
                    user = discord_bridge._discord_users.get(contact_key)
                
                if not user:
                    await update.message.reply_text(
                        f"❌ Could not find a Discord user for contact '{contact_name}'.\n"
                        f"Make sure they have messaged the Discord bot first."
                    )
                    return

                # Polish message
                from backend.services.llm_service import llm_service
                system_prompt = (
                    "You are JARVIS composing a message on Sir's behalf. "
                    "Sir wants to reply to someone. Take his rough intent and turn it into a "
                    "polished, natural message that sounds like it was written by him — not by an AI. "
                    "Keep his tone, just refine it. Output ONLY the refined message, nothing else."
                )
                refined = await llm_service.get_response(
                    user_message=f"Sir wants to reply to {contact_name}: {message}",
                    system_instructions=system_prompt,
                    inject_memory=False,
                )
                final_message = refined.strip()

                await user.send(final_message)
                await update.message.reply_text(
                    f"✅ Message sent to {contact_name} on Discord:\n\n{final_message}"
                )

            else:
                # Browser-based platforms
                from backend.services.social_reply_service import social_reply_service
                res = await social_reply_service.send_reply(
                    platform=platform,
                    contact_name=contact_name,
                    message=message,
                    polish=True
                )
                if res.get("success"):
                    await update.message.reply_text(
                        f"✅ Message sent to {contact_name} on {platform.capitalize()}:\n\n"
                        f"{res.get('message_sent')}"
                    )
                else:
                    await update.message.reply_text(
                        f"❌ Failed to send message on {platform.capitalize()}: {res.get('error')}\n"
                        f"Drafted message: {res.get('drafted_message', message)}"
                    )

        except Exception as e:
            await update.message.reply_text(f"❌ Error executing reply: {e}")

    async def _cmd_research(self, update: Update, context) -> None:
        """Run a parallel web Research Swarm."""
        if not self._authorize(update):
            return
        query = " ".join(context.args) if context.args else ""
        if not query:
            await update.message.reply_text(
                "Usage: /research <query>\nExample: /research best practices FastAPI deployment"
            )
            return

        await update.message.reply_text(f"🔍 Launching Research Swarm for: {query}...")
        try:
            from backend.services.research_swarm import research_swarm
            result = await research_swarm.run_swarm(query)
            if result.get("success"):
                report = result.get("report", "No report generated.")
                # Telegram has a 4096-char limit per message; chunk if needed
                chunks = self._chunk_text(report, 4000)
                for chunk in chunks:
                    await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(
                    f"⚠️ Research swarm returned no results: {result.get('report', 'Unknown error')}"
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Research failed: {e}")

    async def _handle_text(self, update: Update, context) -> None:
        """Forward plain text to LLM for conversational response."""
        if not self._authorize(update):
            from backend.services.focus_mode import focus_mode_service
            if focus_mode_service.is_active():
                sender_name = update.effective_user.first_name if update.effective_user else "Someone"
                text = update.message.text
                focus_mode_service.queue_message(sender_name, "Telegram", text)
                reply = await focus_mode_service.get_auto_reply(sender_name, text)
                if reply:
                    await update.message.reply_text(reply)
            return

        text = update.message.text
        try:
            from backend.services.llm_service import llm_service

            response = await llm_service.get_response(
                user_message=text,
                system_instructions=(
                    "You are JARVIS, an elite AI assistant connected via Telegram. "
                    "Reply concisely and helpfully. If the user asks you to run a command, "
                    "tell them to use the /task prefix."
                ),
                inject_memory=True,
            )

            chunks = self._chunk_text(response.strip(), 4000)
            for chunk in chunks:
                await update.message.reply_text(chunk)
        except Exception as e:
            log.error("telegram_chat_failed", error=str(e))
            await update.message.reply_text(f"❌ Chat processing failed: {e}")

    @staticmethod
    def _chunk_text(text: str, max_len: int = 4000) -> list:
        """Split text into chunks respecting Telegram's 4096-char message limit."""
        if len(text) <= max_len:
            return [text]
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            split_idx = text.rfind("\n", 0, max_len)
            if split_idx == -1:
                split_idx = max_len
            chunks.append(text[:split_idx])
            text = text[split_idx:].lstrip("\n")
        return chunks


telegram_bridge = TelegramBridge()
