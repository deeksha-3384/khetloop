"""
Telegram long-polling bot. Run with:  python -m backend.bot.bot
Uses plain requests (no webhook, no asyncio). Imported by other backend modules only for send_text().

Security: the bot token is part of every Telegram URL, so errors are logged by TYPE only,
never with the exception text (which would contain the token).
"""
import logging
import time

import requests

from backend.bot.handlers import BotHandler
from backend.config import Config

log = logging.getLogger("khetloop.bot")
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_TEXT = 4000


class TelegramAPI:
    def __init__(self, token: str):
        self.base = "https://api.telegram.org/bot" + token
        self.file_base = "https://api.telegram.org/file/bot" + token

    def _call(self, method, payload=None, files=None, timeout=15):
        try:
            if files:
                r = requests.post(self.base + "/" + method, data=payload, files=files, timeout=timeout)
            else:
                r = requests.post(self.base + "/" + method, json=payload or {}, timeout=timeout)
            data = r.json()
        except Exception as e:
            log.warning("telegram %s failed: %s", method, type(e).__name__)
            return None
        if not data.get("ok"):
            log.warning("telegram %s error code %s", method, data.get("error_code"))
            return None
        return data.get("result")

    def get_me(self):
        return self._call("getMe")

    def delete_webhook(self):
        return self._call("deleteWebhook")

    def get_updates(self, offset, timeout=30):
        return self._call("getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]},
                          timeout=timeout + 10)

    def send_text(self, chat_id, text, keyboard=None) -> bool:
        payload = {"chat_id": chat_id, "text": (text or "")[:MAX_TEXT]}
        if keyboard:
            payload["reply_markup"] = keyboard
        return self._call("sendMessage", payload) is not None

    def send_voice(self, chat_id, path) -> bool:
        try:
            with open(path, "rb") as f:
                return self._call("sendVoice", {"chat_id": chat_id}, files={"voice": f}, timeout=60) is not None
        except OSError:
            return False

    def send_chat_action(self, chat_id, action="typing"):
        self._call("sendChatAction", {"chat_id": chat_id, "action": action})

    def download(self, file_id):
        info = self._call("getFile", {"file_id": file_id})
        if not info or "file_path" not in info or (info.get("file_size") or 0) > MAX_DOWNLOAD_BYTES:
            return None
        try:
            r = requests.get(self.file_base + "/" + info["file_path"], timeout=30)
        except Exception as e:
            log.warning("telegram download failed: %s", type(e).__name__)
            return None
        return r.content if r.status_code == 200 else None


_shared_api = None


def send_text(chat_id, text) -> bool:
    """Used by routes and the pipeline to message a farmer. Returns False if Telegram is not configured."""
    global _shared_api
    if not Config.TELEGRAM_BOT_TOKEN:
        return False
    if _shared_api is None:
        _shared_api = TelegramAPI(Config.TELEGRAM_BOT_TOKEN)
    return _shared_api.send_text(chat_id, text)


def next_offset(updates, current):
    ids = [u.get("update_id") for u in updates if isinstance(u.get("update_id"), int)]
    return max(ids) + 1 if ids else current


def run_polling(api, handler, should_stop=lambda: False, retry_delay=3):
    offset = None
    while not should_stop():
        updates = api.get_updates(offset)
        if updates is None:  # network or Telegram problem: wait a little and try again
            time.sleep(retry_delay)
            continue
        for update in updates:
            try:
                handler.handle_update(update)
            except Exception as e:
                log.warning("update failed: %s", type(e).__name__)
        offset = next_offset(updates, offset)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not Config.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is empty. Create a bot with @BotFather and put the token in .env")
        return
    api = TelegramAPI(Config.TELEGRAM_BOT_TOKEN)
    me = api.get_me()
    if not me:
        print("Could not reach Telegram or the token is wrong. Check TELEGRAM_BOT_TOKEN in .env")
        return
    api.delete_webhook()  # polling does not work while a webhook is set
    print("Bot started as @%s. Press Ctrl+C to stop." % me.get("username"))
    try:
        run_polling(api, BotHandler(api))
    except KeyboardInterrupt:
        print("Bot stopped.")


if __name__ == "__main__":
    main()