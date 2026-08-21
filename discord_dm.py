"""Sends a DM (optionally with a file attachment) via the Discord bot's
REST API. Reuses the same bot token as the capture bot."""
import os
import requests

API_BASE = "https://discord.com/api/v10"


def _headers():
    return {"Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}"}


def _open_dm_channel(user_id: str) -> str:
    res = requests.post(
        f"{API_BASE}/users/@me/channels",
        headers=_headers(),
        json={"recipient_id": user_id},
    )
    res.raise_for_status()
    return res.json()["id"]


def send_dm(user_id: str, content: str, filename: str = None, file_bytes: bytes = None):
    channel_id = _open_dm_channel(user_id)
    url = f"{API_BASE}/channels/{channel_id}/messages"

    if file_bytes and filename:
        files = {
            "file": (filename, file_bytes,
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        }
        data = {"content": content}
        res = requests.post(url, headers=_headers(), data=data, files=files)
    else:
        res = requests.post(url, headers=_headers(), json={"content": content})

    res.raise_for_status()
    return res.json()


def send_dm_to_team(content: str, filename: str = None, file_bytes: bytes = None):
    """Sends to both Naldo and Jason."""
    for env_var in ("NALDO_DISCORD_USER_ID", "JASON_DISCORD_USER_ID"):
        user_id = os.environ.get(env_var)
        if user_id:
            send_dm(user_id, content, filename, file_bytes)
