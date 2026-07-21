# JARVIS OMEGA - Phone Agent (Phase 16) — Free: TTS → WhatsApp voice note
from __future__ import annotations
import base64
from pathlib import Path
from typing import Any, Dict
from backend.tools import tool, RiskTier

@tool(name="phone.voice_message", description="Generate an Arabic voice message and send via WhatsApp. FREE — no Twilio needed.", parameters={"type":"object","properties":{"text":{"type":"string"},"recipient":{"type":"string","default":"","description":"Phone number. Empty = just generate the file."},"voice":{"type":"string","default":"ar-JZ-AyoubNeural"}},"required":["text"]}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="phone_agent")
async def voice_message(text: str, recipient: str = "", voice: str = "ar-JZ-AyoubNeural") -> Dict[str, Any]:
    from plugins.voice_local.plugin import voice_tts_edge
    result = await voice_tts_edge(text=text, voice=voice)
    if not result.get("ok"): return result
    audio_b64 = result["audio_base64"]
    # If recipient given, send via WhatsApp
    if recipient:
        import plugins.whatsapp.plugin as wa
        # Save temp file then send via WhatsApp
        tmp = Path("./storage/phone_agent/temp_voice.mp3")
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(base64.b64decode(audio_b64))
        send = await wa.whatsapp_send_image(recipient=recipient, image_path=str(tmp), caption="🎙️ رسالة صوتية من JARVIS")
        return {"ok": send.get("ok",False), "sent": send.get("ok",False), "voice": voice, "text": text[:100]}
    return {"ok": True, "audio_base64": audio_b64, "format": "mp3", "voice": voice}

@tool(name="phone.call_twilio", description="Make a real phone call in Arabic. Uses Twilio free trial ($15 credit). Requires twilio_account_sid + twilio_auth_token + twilio_phone_number.", parameters={"type":"object","properties":{"to":{"type":"string","description":"Phone in international format (9627XXX...)"}},"required":["to"]}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="phone_agent")
async def call_twilio(to: str) -> Dict[str, Any]:
    try:
        from twilio.rest import Client
    except ImportError:
        return {"ok": False, "error": "twilio not installed — pip install twilio"}
    sid = _cred("twilio_account_sid"); token = _cred("twilio_auth_token"); frm = _cred("twilio_phone_number")
    if not all([sid,token,frm]): return {"ok": False, "error": "twilio creds not in vault. Free trial: https://twilio.com"}
    try:
        client = Client(sid, token)
        call = client.calls.create(
            twiml='<Response><Say language="ar-SA">مرحباً، هذا JARVIS. أتصل نيابة عن سيدي. شكراً لوقتك.</Say></Response>',
            to=to, from_=frm)
        return {"ok": True, "call_sid": call.sid, "to": to}
    except Exception as e: return {"ok": False, "error": str(e)}

@tool(name="phone.sms", description="Send an SMS. Twilio free trial includes SMS.", parameters={"type":"object","properties":{"to":{"type":"string"},"body":{"type":"string"}},"required":["to","body"]}, risk_tier=RiskTier.TIER_4_EXTERNAL, category="phone_agent")
async def sms(to: str, body: str) -> Dict[str, Any]:
    try:
        from twilio.rest import Client
    except ImportError:
        return {"ok": False, "error": "twilio not installed"}
    sid = _cred("twilio_account_sid"); token = _cred("twilio_auth_token"); frm = _cred("twilio_phone_number")
    if not all([sid,token,frm]): return {"ok": False, "error": "twilio creds not in vault"}
    try:
        client = Client(sid, token)
        msg = client.messages.create(body=body[:160], to=to, from_=frm)
        return {"ok": True, "sid": msg.sid}
    except Exception as e: return {"ok": False, "error": str(e)}

def _cred(k):
    try:
        from backend.services.credentials_vault import credentials_vault
        return credentials_vault.get(k) or None
    except: return None

PLUGIN_NAME = "phone_agent"; PLUGIN_VERSION = "1.0.0"
PLUGIN_DESCRIPTION = "Phone agent: Arabic voice messages via WhatsApp (free), Twilio calls + SMS (free trial)."
