"""Sends a DM (optionally with a file attachment) via the Discord bot's
REST API. Reuses the same bot token as the capture bot."""
import os
import requests

API_BASE = "https://discord.com/api/v10"

# Discord rejects a message whose content exceeds 2000 characters with a
# 400. Anything built from report data is unbounded, so it must be split
# before sending, never sent and hoped for.
MAX_CONTENT = 2000


def _headers():
    return {"Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}"}


def split_content(text: str, limit: int = MAX_CONTENT):
    """Splits text into <=limit chunks, preferring line boundaries."""
    chunks, current = [], ""
    for line in (text or "").split("\n"):
        while len(line) > limit:                    # single over-long line
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _open_dm_channel(user_id: str) -> str:
    res = requests.post(
        f"{API_BASE}/users/@me/channels",
        headers=_headers(),
        json={"recipient_id": user_id},
    )
    res.raise_for_status()
    return res.json()["id"]


def send_dm(user_id: str, content: str, filename: str = None, file_bytes: bytes = None):
    """Sends one message. The attachment always rides the FIRST message;
    any content past the limit follows as plain messages, so an over-long
    body can never stop the attachment from being delivered."""
    channel_id = _open_dm_channel(user_id)
    url = f"{API_BASE}/channels/{channel_id}/messages"

    parts = split_content(content) or [""]
    first, rest = parts[0], parts[1:]

    if file_bytes and filename:
        files = {
            "file": (filename, file_bytes,
                     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        }
        res = requests.post(url, headers=_headers(), data={"content": first}, files=files)
    else:
        res = requests.post(url, headers=_headers(), json={"content": first})
    res.raise_for_status()
    out = res.json()

    for part in rest:
        follow = requests.post(url, headers=_headers(), json={"content": part})
        follow.raise_for_status()
    return out


def send_dm_to_team(content: str, filename: str = None, file_bytes: bytes = None):
    """Sends to both Naldo and Jason."""
    for env_var in ("NALDO_DISCORD_USER_ID", "JASON_DISCORD_USER_ID"):
        user_id = os.environ.get(env_var)
        if user_id:
            send_dm(user_id, content, filename, file_bytes)
