# ====================================================================
# JARVIS OMEGA — Discord Bridge Service
# ====================================================================
"""
Discord Bridge Service.
Connects JARVIS to a Discord bot for remote command execution,
system monitoring, focus mode control, and conversational AI access.
Mirrors the Telegram Bridge feature set for Discord users.
"""

from __future__ import annotations

import asyncio
import io
import os
from typing import Optional, Dict, Any

from backend.config import settings
from backend.vault.secure_vault import secure_vault
from shared.logger import get_logger

log = get_logger("discord_bridge")

# Command descriptions for /help
COMMANDS: Dict[str, str] = {
    "!screen": "Capture and send a screenshot of the desktop",
    "!status": "Get system vitals (CPU / RAM / Disk)",
    "!task <command>": "Execute an OS-level command (e.g. `!task open chrome`)",
    "!focus [note] [minutes]": "Activate Focus Mode (e.g. `!focus Studying 60`)",
    "!focus off": "Deactivate Focus Mode and get missed-message summary",
    "!research <query>": "Run a parallel web Research Swarm and return a report",
    "!reply <message>": "Compose a polished reply on your behalf (e.g. `!reply John Hey, see you at 5`)",
    "!vault list": "List secret keys stored in the Secure Vault",
    "!chaos": "Trigger a Chaos Monkey resilience test (if enabled)",
    "!help": "Show this help message",
}


class DiscordBridge:
    """
    Discord bot for remote device access.
    Allows Sir to send commands, view screenshots, and monitor vitals
    from any Discord server or DM channel.
    """

    def __init__(self) -> None:
        self._client: Any = None  # discord.Client instance
        self._allowed_user_id: Optional[int] = None
        self._running: bool = False
        self._guild_id: Optional[int] = None
        self._discord_users: Dict[str, Any] = {}

    async def start(self) -> None:
        """Start the Discord bot. Requires DISCORD_BOT_TOKEN in vault or env."""
        bot_token = secure_vault.retrieve("DISCORD_BOT_TOKEN") or os.environ.get("DISCORD_BOT_TOKEN")
        if not bot_token:
            log.warning("discord_missing_token_skipping")
            return

        # Allow restricting to a specific Discord user ID
        allowed_uid = os.environ.get("DISCORD_ALLOWED_USER_ID")
        if allowed_uid:
            try:
                self._allowed_user_id = int(allowed_uid)
            except ValueError:
                log.warning("discord_invalid_allowed_user_id", raw=allowed_uid)

        # Optionally restrict to a specific guild/server
        guild_id = os.environ.get("DISCORD_GUILD_ID")
        if guild_id:
            try:
                self._guild_id = int(guild_id)
            except ValueError:
                pass

        try:
            import discord

            intents = discord.Intents.default()
            intents.message_content = True
            intents.guilds = True

            client = discord.Client(intents=intents)

            @client.event
            async def on_ready():
                log.info("discord_bridge_connected", user=str(client.user), guilds=len(client.guilds))
                self._running = True

            @client.event
            async def on_message(message: discord.Message):
                # Ignore the bot's own messages
                if message.author == client.user:
                    return

                # Record user info for replying
                self._record_user(message)

                # Authorization gate
                if self._allowed_user_id and message.author.id != self._allowed_user_id:
                    # If Focus Mode is active, queue + auto-reply for non-authorized users
                    await self._handle_unauthorized_message(message)
                    return

                # Guild restriction
                if self._guild_id and message.guild and message.guild.id != self._guild_id:
                    return

                # Auto-register the first user as the owner if none set
                if not self._allowed_user_id:
                    self._allowed_user_id = message.author.id
                    log.info("discord_owner_auto_registered", user_id=message.author.id)

                content = message.content.strip()

                # Route commands
                if content.startswith("!"):
                    await self._route_command(message, content)
                else:
                    # Plain text — treat as conversational AI query
                    await self._handle_chat(message, content)

            self._client = client

            # Run the bot in the background (non-blocking)
            asyncio.create_task(self._run_bot(client, bot_token))
            log.info("discord_bridge_starting")

        except ImportError:
            log.warning("discord_py_not_installed_skipping_bridge")
        except Exception as e:
            log.error("discord_bridge_start_failed", error=str(e))

    async def _run_bot(self, client: Any, token: str) -> None:
        """Run the discord client, reconnecting on failure."""
        max_retries = 5
        retry_count = 0
        while retry_count < max_retries:
            try:
                await client.start(token)
            except Exception as e:
                retry_count += 1
                log.error("discord_bot_disconnected", error=str(e), retry=retry_count)
                await asyncio.sleep(min(30, 5 * retry_count))
        log.critical("discord_bot_max_retries_exceeded")

    def _record_user(self, message: Any) -> None:
        """Record mapping of user names to User objects for replying."""
        if not message or not message.author:
            return
        author = message.author
        username = author.name.lower()
        self._discord_users[username] = author
        self._discord_users[f"@{username}"] = author
        
        display_name = author.display_name.lower()
        self._discord_users[display_name] = author
        self._discord_users[f"@{display_name}"] = author
        
        if hasattr(author, "discriminator") and author.discriminator and author.discriminator != "0":
            full_user = f"{author.name}#{author.discriminator}".lower()
            self._discord_users[full_user] = author

    async def stop(self) -> None:
        """Gracefully shut down the Discord bot."""
        if self._client:
            await self._client.close()
        self._running = False
        log.info("discord_bridge_stopped")

    # ----------------------------------------------------------------
    # Command Router
    # ----------------------------------------------------------------
    async def _route_command(self, message: Any, content: str) -> None:
        """Parse and dispatch a !command message."""
        parts = content.split(maxsplit=1)
        cmd = parts[0].lower()
        args_str = parts[1] if len(parts) > 1 else ""

        handlers = {
            "!help": self._cmd_help,
            "!screen": self._cmd_screen,
            "!status": self._cmd_status,
            "!task": self._cmd_task,
            "!focus": self._cmd_focus,
            "!research": self._cmd_research,
            "!reply": self._cmd_reply,
            "!vault": self._cmd_vault,
            "!chaos": self._cmd_chaos,
        }

        handler = handlers.get(cmd)
        if handler:
            try:
                await handler(message, args_str)
            except Exception as e:
                log.error("discord_command_failed", cmd=cmd, error=str(e))
                await message.channel.send(f"⚠️ Command `{cmd}` failed: {e}")
        else:
            await message.channel.send(
                f"❓ Unknown command `{cmd}`. Use `!help` to see available commands."
            )

    # ----------------------------------------------------------------
    # Command Handlers
    # ----------------------------------------------------------------
    async def _cmd_help(self, message: Any, args: str) -> None:
        help_lines = [f"**{cmd}** — {desc}" for cmd, desc in COMMANDS.items()]
        embed_text = "\n".join(help_lines)
        await message.channel.send(
            f"🤖 **J.A.R.V.I.S. OMEGA — Discord Command Center**\n\n{embed_text}"
        )

    async def _cmd_screen(self, message: Any, args: str) -> None:
        await message.channel.send("📸 Capturing screen, Sir...")
        try:
            from local_client.screenshot_manager import screenshot_manager
            img_bytes = screenshot_manager.capture()
            import discord
            file = discord.File(fp=io.BytesIO(img_bytes), filename="screenshot.png")
            await message.channel.send(file=file)
        except Exception as e:
            await message.channel.send(f"❌ Failed to capture screen: {e}")

    async def _cmd_status(self, message: Any, args: str) -> None:
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            msg = (
                f"📊 **System Status**\n"
                f"```\n"
                f"CPU:  {cpu}%\n"
                f"RAM:  {mem.percent}% ({mem.used // (1024**2)}MB / {mem.total // (1024**2)}MB)\n"
                f"DISK: {disk.percent}% ({disk.used // (1024**3)}GB / {disk.total // (1024**3)}GB)\n"
                f"```"
            )
            await message.channel.send(msg)
        except Exception as e:
            await message.channel.send(f"❌ Status check failed: {e}")

    async def _cmd_task(self, message: Any, args: str) -> None:
        if not args:
            await message.channel.send("Usage: `!task <command>`\nExample: `!task open chrome`")
            return

        await message.channel.send(f"⚙️ Executing: `{args}`")
        try:
            from backend.services.command_interpreter import command_interpreter
            import subprocess

            commands = command_interpreter.interpret(args)
            if commands:
                results = []
                for desc, shell_cmd in commands:
                    proc = subprocess.run(
                        shell_cmd, shell=True, capture_output=True, text=True, timeout=15
                    )
                    output = proc.stdout[:800] if proc.stdout else (
                        proc.stderr[:800] if proc.stderr else "Done."
                    )
                    results.append(f"**{desc}**\n```\n{output}\n```")
                await message.channel.send("\n".join(results))
            else:
                await message.channel.send("❓ No matching command found for that request.")
        except Exception as e:
            await message.channel.send(f"❌ Execution failed: {e}")

    async def _cmd_focus(self, message: Any, args: str) -> None:
        from backend.services.focus_mode import focus_mode_service

        if not args:
            status = focus_mode_service.get_status()
            if status["active"]:
                rem = ""
                if status["time_remaining_seconds"]:
                    rem = f" ({int(status['time_remaining_seconds'] // 60)}m remaining)"
                await message.channel.send(
                    f"🎯 Focus Mode is **active**: *{status['focus_note']}*{rem}\n"
                    f"To turn it off: `!focus off`"
                )
            else:
                await message.channel.send(
                    "💤 Focus Mode is currently **inactive**.\n"
                    "Usage: `!focus <note> [duration_minutes]`\n"
                    "Example: `!focus Working on project 60`"
                )
            return

        action = args.split()[0].lower()
        if action in ("off", "deactivate", "stop"):
            res = focus_mode_service.deactivate()
            if res.get("queued_count", 0) > 0:
                await message.channel.send(
                    "✅ Focus Mode deactivated. Summarizing missed messages..."
                )
                summary = await focus_mode_service.generate_queued_summary()
                await message.channel.send(f"📋 **Missed Messages Summary:**\n{summary}")
            else:
                await message.channel.send("✅ Focus Mode deactivated. No missed messages.")
            return

        # Activate
        words = args.split()
        duration = None
        note_words = list(words)
        if len(words) > 1 and words[-1].isdigit():
            duration = int(words[-1])
            note_words = words[:-1]

        note = " ".join(note_words)
        focus_mode_service.activate(note, duration_minutes=duration)

        duration_msg = f" for **{duration} minutes**" if duration else ""
        await message.channel.send(f"🎯 Focus Mode activated: *{note}*{duration_msg}")

    async def _cmd_research(self, message: Any, args: str) -> None:
        if not args:
            await message.channel.send("Usage: `!research <query>`\nExample: `!research best practices FastAPI deployment`")
            return

        await message.channel.send(f"🔍 Launching Research Swarm for: *{args}*...")
        try:
            from backend.services.research_swarm import research_swarm
            result = await research_swarm.run_swarm(args)
            if result.get("success"):
                report = result.get("report", "No report generated.")
                # Discord has a 2000-char limit per message; chunk if needed
                chunks = self._chunk_text(report, 1900)
                for chunk in chunks:
                    await message.channel.send(chunk)
            else:
                await message.channel.send(f"⚠️ Research swarm returned no results: {result.get('report', 'Unknown error')}")
        except Exception as e:
            await message.channel.send(f"❌ Research failed: {e}")

    async def _cmd_vault(self, message: Any, args: str) -> None:
        action = args.strip().lower() if args else "list"
        if action == "list":
            keys = secure_vault.list_keys()
            if keys:
                key_list = "\n".join(f"• `{k}`" for k in keys)
                await message.channel.send(f"🔐 **Vault Keys:**\n{key_list}")
            else:
                await message.channel.send("🔐 Vault is empty — no secrets stored.")
        else:
            await message.channel.send("Usage: `!vault list`\n(Retrieval/storage via Discord disabled for security)")

    async def _cmd_chaos(self, message: Any, args: str) -> None:
        from backend.services.chaos_monkey import chaos_monkey

        if not chaos_monkey.enabled:
            await message.channel.send("🐒 Chaos Monkey is **disabled**. Set `CHAOS_MONKEY_ENABLED=true` to activate.")
            return

        await message.channel.send("🐒 Running Chaos Monkey weekly test...")
        try:
            report = await chaos_monkey.run_weekly_chaos_test()
            status = report.get("overall_status", "UNKNOWN")
            passed = report.get("tests_passed", 0)
            total = report.get("tests_run", 0)
            emoji = "✅" if status == "STABLE" else "⚠️"
            await message.channel.send(
                f"{emoji} **Chaos Test Complete**\n"
                f"Status: `{status}` — {passed}/{total} tests passed\n"
                f"Test ID: `{report.get('test_id')}`"
            )
        except Exception as e:
            await message.channel.send(f"❌ Chaos test failed: {e}")

    # ----------------------------------------------------------------
    # Conversational AI Chat
    # ----------------------------------------------------------------
    async def _cmd_reply(self, message: Any, args: str) -> None:
        """Compose and send a polished reply on behalf of Sir."""
        if not args:
            await message.channel.send(
                "Usage: `!reply [platform] <contact_name> <message>`\n"
                "Platforms: whatsapp, instagram, messenger, x, discord, telegram\n"
                "Example: `!reply whatsapp John Hey, I'll be late`\n"
                "Or: `!reply John Hey, I'll be late` (auto-detects platform)"
            )
            return

        import shlex
        try:
            try:
                parts = shlex.split(args)
            except Exception:
                parts = args.split()

            if len(parts) < 2:
                await message.channel.send(
                    "Usage: `!reply [platform] <contact_name> <message>`\n"
                    "Please provide both a contact name and a message."
                )
                return

            first_arg = parts[0].lower()
            supported_platforms = ["whatsapp", "instagram", "messenger", "x", "telegram", "discord"]

            if first_arg in supported_platforms:
                platform = first_arg
                contact_name = parts[1]
                msg_content = " ".join(parts[2:])
            else:
                contact_name = parts[0]
                msg_content = " ".join(parts[1:])
                # Auto-detect platform
                platform = None
                contact_lower = contact_name.lower().lstrip('@')

                # Check discord users
                if contact_lower in self._discord_users or f"@{contact_lower}" in self._discord_users:
                    platform = "discord"
                else:
                    # Check telegram chats
                    from backend.telegram_app.telegram_bridge import telegram_bridge
                    if hasattr(telegram_bridge, "_telegram_chats"):
                        if contact_lower in telegram_bridge._telegram_chats or f"@{contact_lower}" in telegram_bridge._telegram_chats:
                            platform = "telegram"

                    if not platform:
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

            await message.channel.send(
                f"⚙️ Processing reply on platform **{platform}** for **{contact_name}**..."
            )

            # Route to platform
            if platform == "discord":
                contact_key = contact_name.lower().lstrip('@')
                user = self._discord_users.get(contact_key) or self._discord_users.get(f"@{contact_key}")
                if not user:
                    await message.channel.send(
                        f"❌ Could not find a Discord user for '{contact_name}'.\n"
                        f"Make sure they have messaged the bot first."
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
                    user_message=f"Sir wants to reply to {contact_name}: {msg_content}",
                    system_instructions=system_prompt,
                    inject_memory=False,
                )
                final_message = refined.strip()

                await user.send(final_message)
                await message.channel.send(
                    f"✅ Message sent to {contact_name} on Discord:\n\n{final_message}"
                )

            elif platform == "telegram":
                from backend.telegram_app.telegram_bridge import telegram_bridge
                contact_key = contact_name.lower().lstrip('@')
                chat_id = None
                if hasattr(telegram_bridge, "_telegram_chats"):
                    chat_id = telegram_bridge._telegram_chats.get(contact_key) or telegram_bridge._telegram_chats.get(f"@{contact_key}")

                if not chat_id or not hasattr(telegram_bridge, "_bot") or not telegram_bridge._bot:
                    await message.channel.send(
                        f"❌ Could not find an active Telegram session/chat ID for '{contact_name}'."
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
                    user_message=f"Sir wants to reply to {contact_name}: {msg_content}",
                    system_instructions=system_prompt,
                    inject_memory=False,
                )
                final_message = refined.strip()

                await telegram_bridge._bot.send_message(chat_id=chat_id, text=final_message)
                await message.channel.send(
                    f"✅ Message sent to {contact_name} on Telegram:\n\n{final_message}"
                )

            else:
                # Browser-based platforms
                from backend.services.social_reply_service import social_reply_service
                res = await social_reply_service.send_reply(
                    platform=platform,
                    contact_name=contact_name,
                    message=msg_content,
                    polish=True
                )
                if res.get("success"):
                    await message.channel.send(
                        f"✅ Message sent to {contact_name} on {platform.capitalize()}:\n\n"
                        f"{res.get('message_sent')}"
                    )
                else:
                    await message.channel.send(
                        f"❌ Failed to send message on {platform.capitalize()}: {res.get('error')}\n"
                        f"Drafted message: {res.get('drafted_message', msg_content)}"
                    )

        except Exception as e:
            await message.channel.send(f"❌ Error executing reply: {e}")

    # ----------------------------------------------------------------
    # Conversational AI Chat (plain text)
    # ----------------------------------------------------------------
    async def _handle_chat(self, message: Any, content: str) -> None:
        """Forward plain text to the LLM for conversational response."""
        try:
            from backend.services.llm_service import llm_service

            async with message.channel.typing():
                response = await llm_service.get_response(
                    user_message=content,
                    system_instructions=(
                        "You are JARVIS, an elite AI assistant connected via Discord. "
                        "Reply concisely and helpfully. If the user asks you to run a command, "
                        "tell them to use the !task prefix."
                    ),
                    inject_memory=True,
                )

            chunks = self._chunk_text(response.strip(), 1900)
            for chunk in chunks:
                await message.channel.send(chunk)

        except Exception as e:
            log.error("discord_chat_failed", error=str(e))
            await message.channel.send(f"❌ Chat processing failed: {e}")

    # ----------------------------------------------------------------
    # Unauthorized User Handler (Focus Mode integration)
    # ----------------------------------------------------------------
    async def _handle_unauthorized_message(self, message: Any) -> None:
        """Queue messages from unauthorized users during Focus Mode and auto-reply."""
        try:
            from backend.services.focus_mode import focus_mode_service

            if focus_mode_service.is_active():
                sender_name = str(message.author)
                text = message.content
                focus_mode_service.queue_message(sender_name, "Discord", text)

                if not focus_mode_service.is_excluded(str(message.author.id)):
                    reply = await focus_mode_service.get_auto_reply(sender_name, text)
                    if reply:
                        await message.channel.send(reply)
        except Exception:
            pass  # Silently skip — unauthorized user, no need to surface errors

    # ----------------------------------------------------------------
    # Utilities
    # ----------------------------------------------------------------
    @staticmethod
    def _chunk_text(text: str, max_len: int = 1900) -> list[str]:
        """Split text into chunks respecting Discord's 2000-char message limit."""
        if len(text) <= max_len:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            # Try to split at a newline
            split_idx = text.rfind("\n", 0, max_len)
            if split_idx == -1:
                split_idx = max_len
            chunks.append(text[:split_idx])
            text = text[split_idx:].lstrip("\n")
        return chunks

    @property
    def is_running(self) -> bool:
        return self._running


# Singleton
discord_bridge = DiscordBridge()
