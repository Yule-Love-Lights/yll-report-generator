"""Turns a Daily report's structured action items into Vikunja tasks.

Runs as a step inside the existing daily job (see main.py) — it consumes the
same `report` dict that docx_renderer renders, so nothing ever has to parse
the finished Word document.

Dedup is three layers, cheapest first:
  1. Per-date guard  — a date already fully synced is skipped on a rerun.
  2. Exact fingerprint — every auto-created task carries a `yll-sync-id`
     marker in its description, so an identically-worded item is matched
     locally with no API or model cost.
  3. Semantic match — whatever is left is handed to Claude together with the
     currently-open task list, which is the only thing that reliably catches
     a rollover that got reworded ("call the HOA back" -> "follow up with
     Palm Beach HOA").

Rollovers are never re-created; they get a comment on the existing task so
the aging history stays in one place. Items the report says were finished
out loud are moved to the "Auto Closed" bucket rather than marked done, so
a human still confirms before they land in "Done".
"""
import html
import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from anthropic import Anthropic
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

from drive_helpers import list_files, download_json
from vikunja_client import VikunjaClient, VikunjaError

TZ = ZoneInfo("America/New_York")
INDEX_FILENAME = "vikunja_task_index.json"
SYNC_ID_RE = re.compile(r"yll-sync-id:\s*([0-9a-f]{12})")

PROJECT_NAME = os.environ.get("VIKUNJA_PROJECT_NAME", "Tasks from Reports")
MAX_NEW_TASKS = int(os.environ.get("VIKUNJA_SYNC_MAX_NEW_TASKS", "15"))
MODEL = os.environ.get("VIKUNJA_SYNC_MODEL", "claude-opus-5")

# Report owner key -> kanban bucket title. Anything unrecognised falls back
# to the catch-all bucket.
OWNER_BUCKETS = {
    "jason": "For Jason",
    "naldo": "For Naldo",
    "both": "For Anyone",
    "tj_social": "For Anyone",
}
FALLBACK_BUCKET = "For Anyone"
AUTO_CLOSED_BUCKET = "Auto Closed"
AUTO_LABEL = "auto"

# Report owner key -> which Vikunja usernames get assigned. TJ has no
# account, so his items land in the shared bucket unassigned.
OWNER_ASSIGNEES = {
    "jason": ["VIKUNJA_USERNAME_JASON"],
    "naldo": ["VIKUNJA_USERNAME_NALDO"],
    "both": ["VIKUNJA_USERNAME_JASON", "VIKUNJA_USERNAME_NALDO"],
    "tj_social": [],
}

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["new", "duplicate", "skip"]},
                    "existing_task_id": {"type": ["integer", "null"]},
                    "title": {"type": "string"},
                    "due_date": {"type": ["string", "null"]},
                    "priority": {"type": "integer"},
                    "confidence": {"type": "string", "enum": ["high", "low"]},
                    "reason": {"type": "string"},
                },
                "required": ["index", "verdict", "existing_task_id", "title",
                             "due_date", "priority", "confidence", "reason"],
                "additionalProperties": False,
            },
        },
        "closures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["task_id", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["items", "closures"],
    "additionalProperties": False,
}

CLASSIFY_SYSTEM = """You maintain a Kanban board from the daily ops reports of a
holiday-lighting company. You are given the action items pulled out of one
day's report and the tasks currently open on the board. Decide, for each
action item, whether it is genuinely new work or a restatement of something
already on the board.

Rules:
- The same piece of work is described differently from day to day. "Call the
  HOA back", "follow up with Palm Beach HOA" and "chase the HOA on the
  proposal" are the SAME task. Match on the underlying work, not the wording.
- verdict "duplicate" -> set existing_task_id to the open task it restates.
- verdict "new" -> existing_task_id must be null. Write `title` as a short
  imperative task title (under ~80 characters), e.g. "Follow up with Palm
  Beach HOA on the proposal". Do not copy the report's sentence verbatim if
  it is long or conversational.
- verdict "skip" -> use for anything that is not real assignable work:
  musings, "we should think about X someday", restatements of a decision
  with no action, or items too garbled to act on. Prefer skip over guessing.
- confidence "high" only when you are sure the item is real, actionable work
  and your new/duplicate call is right. Anything you are unsure about gets
  "low" — low-confidence items are reported to the humans instead of being
  written to the board, so it is cheap to be cautious.
- due_date: "YYYY-MM-DD" only if the report actually states or clearly
  implies a deadline. Otherwise null. Never invent one.
- priority: 0 unset, 1 low, 2 medium, 3 high. Use 3 only for something the
  report frames as urgent or customer-blocking.
- closures: if the source says a piece of work is already finished, list the
  matching open task's id with a short quote-grounded reason. Only include a
  closure when the report states it was DONE, not merely worked on or
  discussed. If nothing closed, return an empty array.

Never invent work that is not in the source text."""


def _enabled():
    return os.environ.get("VIKUNJA_SYNC_ENABLED", "true").lower() not in ("false", "0", "no")


def _dry_run():
    return os.environ.get("VIKUNJA_SYNC_DRY_RUN", "false").lower() in ("true", "1", "yes")


def _forced():
    return os.environ.get("VIKUNJA_SYNC_FORCE", "false").lower() in ("true", "1", "yes")


def _fingerprint(owner, text):
    norm = re.sub(r"[^a-z0-9 ]+", " ", f"{owner} {text}".lower())
    norm = " ".join(norm.split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def _to_rfc3339(date_str):
    """'YYYY-MM-DD' -> RFC3339 UTC at 5pm Eastern on that day."""
    try:
        d = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
    except (ValueError, AttributeError):
        return None
    local = d.replace(hour=17, tzinfo=TZ)
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _flatten_action_items(report):
    """master_action_list is {owner: [{item, date_raised, age_note?}]}."""
    out = []
    for owner, entries in (report.get("master_action_list") or {}).items():
        for entry in entries or []:
            text = (entry.get("item") if isinstance(entry, dict) else str(entry)) or ""
            text = text.strip()
            if not text:
                continue
            out.append({
                "owner": owner,
                "owner_key": owner.strip().lower(),
                "text": text,
                "date_raised": (entry.get("date_raised") if isinstance(entry, dict) else "") or "",
            })
    return out


def _description_html(source_text, owner, date_str, fingerprint):
    return (
        f"<p>{html.escape(source_text)}</p>"
        f"<p><em>Auto-created from the YLL daily ops report for {html.escape(date_str)} "
        f"(owner in report: {html.escape(owner)}).</em></p>"
        f"<p><code>yll-sync-id: {fingerprint}</code></p>"
    )


# --- persisted index -----------------------------------------------------
#
# Drive's file *list* is only eventually consistent with its file *store*: a
# file can be listed seconds before it can be fetched or deleted. So the
# index is written by updating one long-lived file in place rather than
# delete-then-recreate — that keeps the id stable and never opens a window
# where a listed id 404s. Reads tolerate a stale listing for the same reason.
# Losing the index is survivable anyway: every auto-created task carries its
# fingerprint in its own description, so dedup rebuilds from the board.

def _find_index_file(drive, folder_id):
    for f in list_files(drive, folder_id, name_prefix=INDEX_FILENAME):
        if f["name"] == INDEX_FILENAME:
            return f
    return None


def _load_index(drive, folder_id):
    empty = {"tasks": {}, "synced_dates": []}
    f = _find_index_file(drive, folder_id)
    if not f:
        return empty
    try:
        loaded = download_json(drive, f["id"])
    except Exception as e:
        print(f"Could not read {INDEX_FILENAME} ({e}) — rebuilding dedup from the board.")
        return empty
    loaded.setdefault("tasks", {})
    loaded.setdefault("synced_dates", [])
    return loaded


def _save_index(drive, folder_id, index):
    payload = json.dumps(index, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(payload), mimetype="application/json")
    existing = _find_index_file(drive, folder_id)
    if existing:
        try:
            drive.files().update(
                fileId=existing["id"], media_body=media, supportsAllDrives=True,
            ).execute(num_retries=5)
            return
        except HttpError as e:
            if e.resp.status != 404:
                raise
            # Listed but not yet fetchable, or deleted out from under us.
            print(f"{INDEX_FILENAME} listing was stale — writing a fresh one.")
            media = MediaIoBaseUpload(io.BytesIO(payload), mimetype="application/json")
    drive.files().create(
        body={"name": INDEX_FILENAME, "parents": [folder_id]},
        media_body=media, fields="id", supportsAllDrives=True,
    ).execute(num_retries=5)


def _finish(drive, folder_id, index, date_str, dry):
    """Records the date as done only after a full pass, so a run that blew up
    partway can safely be retried."""
    if dry:
        return
    if date_str not in index.setdefault("synced_dates", []):
        index["synced_dates"].append(date_str)
        index["synced_dates"] = sorted(index["synced_dates"])[-400:]
    _save_index(drive, folder_id, index)


# --- the model call ------------------------------------------------------

def _classify(pending, open_tasks, closed_mentions, date_str):
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    payload = {
        "report_date": date_str,
        "action_items": [
            {"index": i, "owner": p["owner"], "item": p["text"], "date_raised": p["date_raised"]}
            for i, p in enumerate(pending)
        ],
        "open_tasks_on_board": [
            {"task_id": t["id"], "title": t.get("title", "")} for t in open_tasks
        ],
        "report_says_these_closed": closed_mentions,
    }

    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=CLASSIFY_SYSTEM,
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": CLASSIFY_SCHEMA},
        },
        messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


# --- entry point ---------------------------------------------------------

def sync_daily_report(drive, report, date_str, internal_state_folder_id):
    """Pushes one Daily report's action items onto the Vikunja board.

    Returns a summary dict (or None when the sync is switched off / already
    done) that main.py folds into the Discord DM, so the humans always see
    what the board was changed to."""
    if not _enabled():
        print("Vikunja sync disabled (VIKUNJA_SYNC_ENABLED=false) — skipping.")
        return None

    dry = _dry_run()
    summary = {
        "date": date_str, "dry_run": dry, "created": [], "restated": [],
        "auto_closed": [], "needs_review": [], "errors": [],
    }

    index = _load_index(drive, internal_state_folder_id)
    if date_str in index.get("synced_dates", []) and not dry and not _forced():
        print(f"Vikunja sync already completed for {date_str} — skipping "
              f"(set VIKUNJA_SYNC_FORCE=true to redo).")
        return None

    vik = VikunjaClient()
    project = vik.get_project_by_title(PROJECT_NAME)
    view = vik.get_kanban_view(project["id"])
    buckets = vik.get_buckets(project["id"], view["id"])
    users = vik.get_project_users(project["id"])

    required = set(OWNER_BUCKETS.values()) | {FALLBACK_BUCKET, AUTO_CLOSED_BUCKET}
    missing = [b for b in sorted(required) if b.lower() not in buckets]
    if missing:
        raise VikunjaError(
            f"Project {PROJECT_NAME!r} is missing kanban bucket(s): {', '.join(missing)}. "
            f"Found: {', '.join(sorted(buckets))}."
        )

    open_tasks = vik.list_open_tasks(project["id"])
    # Recover fingerprints straight off the board, so the sync still dedupes
    # correctly even if the Drive index file is ever lost.
    live_by_fp = {}
    for t in open_tasks:
        m = SYNC_ID_RE.search(t.get("description") or "")
        if m:
            live_by_fp[m.group(1)] = t

    items = _flatten_action_items(report)
    closed_mentions = [str(c) for c in (report.get("closed_since_last_report") or [])]

    # Layer 2: exact fingerprint match, no model cost.
    pending = []
    for it in items:
        fp = _fingerprint(it["owner_key"], it["text"])
        it["fp"] = fp
        existing = live_by_fp.get(fp)
        if not existing:
            pending.append(it)
            continue
        summary["restated"].append({
            "task_id": existing["id"], "title": existing.get("title", ""),
            "match": "exact", "item": it["text"],
        })
        if not dry:
            try:
                vik.add_comment(
                    existing["id"],
                    f"<p>Raised again in the daily ops report for {html.escape(date_str)}.</p>",
                )
            except VikunjaError as e:
                summary["errors"].append(f"comment on task {existing['id']}: {e}")
        entry = index["tasks"].setdefault(fp, {"task_id": existing["id"], "first_seen": date_str})
        entry["last_seen"] = date_str
        entry["times_raised"] = entry.get("times_raised", 1) + 1

    if not pending and not closed_mentions:
        print(f"Vikunja sync: nothing new for {date_str} ({len(summary['restated'])} restated).")
        _finish(drive, internal_state_folder_id, index, date_str, dry)
        return summary

    # Layer 3: everything left goes to Claude alongside the live board.
    verdicts = _classify(pending, open_tasks, closed_mentions, date_str)
    open_by_id = {t["id"]: t for t in open_tasks}

    created_count = 0
    for v in verdicts.get("items", []):
        idx = v.get("index")
        if not isinstance(idx, int) or not (0 <= idx < len(pending)):
            continue
        it = pending[idx]

        if v["verdict"] == "skip":
            summary["needs_review"].append(
                {"item": it["text"], "why": f"skipped: {v.get('reason', '')}"})
            continue

        if v["confidence"] != "high":
            summary["needs_review"].append(
                {"item": it["text"], "why": f"low confidence: {v.get('reason', '')}"})
            continue

        if v["verdict"] == "duplicate":
            target = open_by_id.get(v.get("existing_task_id"))
            if not target:
                summary["needs_review"].append(
                    {"item": it["text"],
                     "why": "called a duplicate of a task that is not on the board"})
                continue
            summary["restated"].append({
                "task_id": target["id"], "title": target.get("title", ""),
                "match": "semantic", "item": it["text"],
            })
            if not dry:
                try:
                    vik.add_comment(
                        target["id"],
                        f"<p>Restated in the daily ops report for {html.escape(date_str)}: "
                        f"&ldquo;{html.escape(it['text'])}&rdquo;</p>",
                    )
                except VikunjaError as e:
                    summary["errors"].append(f"comment on task {target['id']}: {e}")
            continue

        # verdict == "new"
        if created_count >= MAX_NEW_TASKS:
            summary["needs_review"].append(
                {"item": it["text"], "why": f"daily cap of {MAX_NEW_TASKS} new tasks reached"})
            continue

        bucket_title = OWNER_BUCKETS.get(it["owner_key"], FALLBACK_BUCKET)
        title = (v.get("title") or it["text"]).strip()[:250]
        record = {
            "title": title, "bucket": bucket_title, "owner": it["owner"],
            "due_date": v.get("due_date"), "priority": v.get("priority") or 0,
            "item": it["text"], "task_id": None,
        }

        if dry:
            summary["created"].append(record)
            created_count += 1
            continue

        try:
            task = vik.create_task(
                project["id"], title,
                description=_description_html(it["text"], it["owner"], date_str, it["fp"]),
                due_date=_to_rfc3339(v["due_date"]) if v.get("due_date") else None,
                priority=v.get("priority") or 0,
            )
        except VikunjaError as e:
            summary["errors"].append(f"create {title!r}: {e}")
            continue

        # The task exists from here on. Every later step is best-effort: a
        # failure must still leave the task recorded in the index and the
        # summary, or it becomes an orphan that no future run accounts for.
        problems = []

        def _step(what, fn):
            try:
                fn()
            except VikunjaError as e:
                problems.append(f"{what} ({e})")

        _step("bucket", lambda: vik.move_task_to_bucket(
            project["id"], view["id"], buckets[bucket_title.lower()], task["id"]))
        for env_var in OWNER_ASSIGNEES.get(it["owner_key"], []):
            username = (os.environ.get(env_var) or "").strip().lower()
            if username and username in users:
                _step(f"assign {username}",
                      lambda u=users[username]: vik.assign_user(task["id"], u))
        _step("label", lambda: vik.add_label(task["id"], vik.ensure_label(AUTO_LABEL)))

        record["task_id"] = task["id"]
        record["incomplete"] = problems or None
        if problems:
            summary["errors"].append(
                f"task #{task['id']} {title!r} was created but is incomplete — "
                f"{'; '.join(problems)}")
        summary["created"].append(record)
        created_count += 1
        index["tasks"][it["fp"]] = {
            "task_id": task["id"], "title": title, "owner": it["owner"],
            "first_seen": date_str, "last_seen": date_str, "times_raised": 1,
        }

    # --- auto-closures ---------------------------------------------------
    auto_bucket_id = buckets[AUTO_CLOSED_BUCKET.lower()]
    for c in verdicts.get("closures", []):
        target = open_by_id.get(c.get("task_id"))
        if not target:
            continue
        summary["auto_closed"].append({
            "task_id": target["id"], "title": target.get("title", ""),
            "reason": c.get("reason", ""),
        })
        if dry:
            continue
        try:
            # Deliberately NOT marked done — a human confirms and moves it to
            # "Done" themselves.
            vik.move_task_to_bucket(project["id"], view["id"], auto_bucket_id, target["id"])
            vik.add_comment(
                target["id"],
                f"<p>Moved to <strong>Auto Closed</strong>: the daily ops report for "
                f"{html.escape(date_str)} says this was finished &mdash; "
                f"{html.escape(c.get('reason', ''))}</p><p>Confirm and move it to Done.</p>",
            )
        except VikunjaError as e:
            summary["errors"].append(f"auto-close task {target['id']}: {e}")

    _finish(drive, internal_state_folder_id, index, date_str, dry)
    print(
        f"Vikunja sync for {date_str}: {len(summary['created'])} created, "
        f"{len(summary['restated'])} restated, {len(summary['auto_closed'])} auto-closed, "
        f"{len(summary['needs_review'])} flagged{' (DRY RUN)' if dry else ''}."
    )
    return summary


def format_summary_for_discord(summary):
    """Short plain-text block appended to the daily report DM."""
    if not summary:
        return ""
    lines = ["", f"**Task board** ({PROJECT_NAME})"]
    if summary["dry_run"]:
        lines.append("_DRY RUN — nothing was actually written to the board._")

    for c in summary["created"]:
        due = f" (due {c['due_date']})" if c.get("due_date") else ""
        lines.append(f"• NEW → {c['bucket']}: {c['title']}{due}")
    for r in summary["restated"]:
        lines.append(f"• rolled over (#{r['task_id']}): {r['title']}")
    for a in summary["auto_closed"]:
        lines.append(f"• auto-closed (#{a['task_id']}): {a['title']} — {a['reason']}")
    for n in summary["needs_review"]:
        lines.append(f"• NOT added ({n['why']}): {n['item']}")
    for e in summary["errors"]:
        lines.append(f"• ⚠️ error: {e}")

    if len(lines) == 2:
        lines.append("• no changes")
    return "\n".join(lines)


if __name__ == "__main__":
    # Manual backtest:  python vikunja_sync.py 2026-08-24
    # Replays a past day's already-saved daily state against the live board.
    # Set VIKUNJA_SYNC_DRY_RUN=true first — dry runs write nothing and are
    # never recorded, so you can replay the same day as often as you like.
    import sys
    from drive_helpers import get_drive_service

    if len(sys.argv) != 2:
        sys.exit("usage: python vikunja_sync.py YYYY-MM-DD")

    target = sys.argv[1]
    _drive = get_drive_service()
    _folder = os.environ["GOOGLE_INTERNAL_STATE_FOLDER_ID"]

    _state = next(
        (f for f in list_files(_drive, _folder, name_prefix=f"{target}_daily_state")
         if f["name"].startswith(f"{target}_daily_state")),
        None,
    )
    if not _state:
        sys.exit(f"No saved daily state for {target} in the internal-state folder.")

    _result = sync_daily_report(_drive, download_json(_drive, _state["id"]), target, _folder)
    print(format_summary_for_discord(_result) or "(sync returned nothing)")
