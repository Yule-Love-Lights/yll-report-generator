"""Main entry point. Runs once per day via Railway's Cron Schedule.

The cron fires at BOTH 11:00 and 12:00 UTC (`0 11,12 * * *`). Exactly one
of those is 7am Eastern at any time of year — 11:00 under EDT, 12:00 under
EST — and the other exits immediately at the top of main(). Railway's cron
is UTC and does not follow US daylight saving, so this is what keeps
delivery at 7am year-round without anyone editing the schedule twice a
year. Set FORCE_RUN=true to bypass the hour check for a manual run.

Each run:
  1. Always attempts a Daily report for "yesterday." Skips if zero
     transcript files that day. DMs the finished .docx to Naldo + Jason.
     Not saved to Drive.
  2. If today is Monday: builds a Weekly report for the week that just
     ended (last Monday-Sunday), using that week's raw transcripts plus
     the last few saved Weekly reports for continuity/aging tracking.
     Saves to Drive AND DMs it.
  3. If today is the 1st of the month: builds a Monthly report rolling up
     that month's saved Weekly reports (not raw transcripts). Saves to
     Drive AND DMs it.
"""
import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from drive_helpers import (
    get_drive_service, list_files, download_text, download_bytes,
    upload_docx, upload_json, download_json, delete_files_with_prefix,
)
from report_generator import generate_report
from docx_renderer import render_report_docx
from discord_dm import send_dm_to_team
from vikunja_sync import sync_daily_report, format_summary_for_discord
from docx import Document
import io

TZ = ZoneInfo("America/New_York")

TRANSCRIPTS_FOLDER_ID = os.environ["GOOGLE_TRANSCRIPTS_FOLDER_ID"]
WEEKLY_REPORTS_FOLDER_ID = os.environ["GOOGLE_WEEKLY_REPORTS_FOLDER_ID"]
MONTHLY_REPORTS_FOLDER_ID = os.environ["GOOGLE_MONTHLY_REPORTS_FOLDER_ID"]
# Hidden working folder — not meant for Naldo/Jason to browse. Stores each
# daily report's structured JSON so Weekly can build on it instead of
# re-reading raw transcripts from scratch.
INTERNAL_STATE_FOLDER_ID = os.environ["GOOGLE_INTERNAL_STATE_FOLDER_ID"]

with open(os.path.join(os.path.dirname(__file__), "instructions.md")) as f:
    PROJECT_INSTRUCTIONS = f.read()


def _transcripts_text_for_date(drive, date_str):
    """date_str: 'YYYY-MM-DD'. Returns (session_count, combined_text)."""
    files = list_files(drive, TRANSCRIPTS_FOLDER_ID, name_prefix=date_str)
    files.sort(key=lambda f: f["name"])
    combined = []
    for f in files:
        text = download_text(drive, f["id"])
        combined.append(f"--- {f['name']} ---\n{text}")
    return len(files), "\n\n".join(combined)


def _daily_states_for_range(drive, start_date, end_date):
    """Reads persisted daily-report JSON for each day in range. For any day
    with no saved state (e.g. it predates this pipeline, or something
    failed), falls back to re-reading that day's raw transcripts directly
    so no day silently goes missing from the weekly rollup."""
    all_state_files = list_files(drive, INTERNAL_STATE_FOLDER_ID)
    state_by_date = {f["name"][:10]: f for f in all_state_files}

    parts = []
    total_sessions = 0
    current = datetime.strptime(start_date, "%Y-%m-%d").date()
    end = datetime.strptime(end_date, "%Y-%m-%d").date()

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        if date_str in state_by_date:
            state = download_json(drive, state_by_date[date_str]["id"])
            total_sessions += state.get("session_count", 0)
            parts.append(f"--- Daily report for {date_str} ---\n{json.dumps(state, indent=2)}")
        else:
            # Fallback: no saved daily state for this date, re-read raw
            session_count, raw_text = _transcripts_text_for_date(drive, date_str)
            if session_count > 0:
                total_sessions += session_count
                parts.append(f"--- RAW transcripts for {date_str} (no daily state found) ---\n{raw_text}")
        current += timedelta(days=1)

    return total_sessions, "\n\n".join(parts)


def _transcripts_text_for_range(drive, start_date, end_date):
    """Inclusive date range. Returns (session_count, combined_text)."""
    all_files = list_files(drive, TRANSCRIPTS_FOLDER_ID)
    matching = [
        f for f in all_files
        if start_date <= f["name"][:10] <= end_date
    ]
    matching.sort(key=lambda f: f["name"])
    combined = []
    for f in matching:
        text = download_text(drive, f["id"])
        combined.append(f"--- {f['name']} ---\n{text}")
    return len(matching), "\n\n".join(combined)


def _docx_bytes_to_text(docx_bytes):
    doc = Document(io.BytesIO(docx_bytes))
    return "\n".join(p.text for p in doc.paragraphs)


def _recent_reports_text(drive, folder_id, limit=4):
    files = list_files(drive, folder_id)
    files.sort(key=lambda f: f["name"], reverse=True)
    recent = files[:limit]
    parts = []
    for f in recent:
        content = download_bytes(drive, f["id"])
        parts.append(f"--- {f['name']} ---\n{_docx_bytes_to_text(content)}")
    return "\n\n".join(parts)


def run_daily(drive, today):
    yesterday = today - timedelta(days=1)
    date_str = yesterday.strftime("%Y-%m-%d")
    session_count, source_text = _transcripts_text_for_date(drive, date_str)

    if session_count == 0:
        print(f"No transcripts for {date_str} — skipping daily report.")
        return

    date_range = yesterday.strftime("%A, %B %d, %Y")
    report = generate_report(
        PROJECT_INSTRUCTIONS, "Daily", date_range, session_count, source_text
    )
    docx_bytes = render_report_docx(report)
    filename = f"YLL_Ops_Report_Daily_{date_str}.docx"

    # Persist the structured data (not the polished docx) for Weekly to
    # build on later — this is invisible to Naldo/Jason, purely pipeline state.
    # Clear any prior state for this date first so reruns never leave duplicates.
    removed = delete_files_with_prefix(drive, INTERNAL_STATE_FOLDER_ID, f"{date_str}_daily_state")
    if removed:
        print(f"Removed {removed} existing state file(s) for {date_str} before writing fresh one.")
    upload_json(drive, INTERNAL_STATE_FOLDER_ID, f"{date_str}_daily_state.json", report)

    # Push today's action items onto the Vikunja board. A board problem must
    # never stop the report itself from going out, so this is best-effort and
    # whatever happened (including a failure) is reported in the DM.
    try:
        board_summary = sync_daily_report(drive, report, date_str, INTERNAL_STATE_FOLDER_ID)
        board_note = format_summary_for_discord(board_summary)
    except Exception as e:
        print(f"Vikunja sync failed for {date_str}: {e}")
        board_note = f"\n**Task board** — sync failed, nothing written: {e}"

    # The report goes out on its own first. The board note is built from
    # report data and has no natural length bound, so it must never share a
    # message with the report — an over-long note used to 400 the whole DM
    # and take the report down with it.
    send_dm_to_team(
        f"📋 Daily ops report for {date_range} ({session_count} session(s)) is attached.",
        filename=filename,
        file_bytes=docx_bytes,
    )

    if board_note.strip():
        try:
            send_dm_to_team(board_note)
        except Exception as e:
            print(f"Could not DM the task-board summary for {date_str}: {e}")
    print(f"Daily report for {date_str} generated and sent.")


def run_weekly(drive, today):
    # today is Monday; the week that just ended is last Mon-Sun
    last_sunday = today - timedelta(days=1)
    last_monday = last_sunday - timedelta(days=6)
    start_str = last_monday.strftime("%Y-%m-%d")
    end_str = last_sunday.strftime("%Y-%m-%d")

    session_count, source_text = _daily_states_for_range(drive, start_str, end_str)
    if session_count == 0:
        print(f"No transcripts for week {start_str} to {end_str} — skipping weekly report.")
        return

    date_range = f"{last_monday.strftime('%B %d')} - {last_sunday.strftime('%B %d, %Y')}"
    prior_reports_text = _recent_reports_text(drive, WEEKLY_REPORTS_FOLDER_ID, limit=4)

    report = generate_report(
        PROJECT_INSTRUCTIONS, "Weekly", date_range, session_count,
        source_text, prior_reports_text=prior_reports_text,
    )
    docx_bytes = render_report_docx(report)
    filename = f"YLL_Ops_Report_Weekly_{start_str}_to_{end_str}.docx"

    removed = delete_files_with_prefix(drive, WEEKLY_REPORTS_FOLDER_ID, filename)
    if removed:
        print(f"Removed {removed} existing weekly report(s) for this range before writing fresh one.")
    upload_docx(drive, WEEKLY_REPORTS_FOLDER_ID, filename, docx_bytes)
    send_dm_to_team(
        f"📊 Weekly ops report for {date_range} ({session_count} session(s)) is attached and saved to Drive.",
        filename=filename,
        file_bytes=docx_bytes,
    )
    print(f"Weekly report for {start_str} to {end_str} generated, saved, and sent.")


def run_monthly(drive, today):
    # today is the 1st; the month that just ended is last month
    last_day_of_prev_month = today - timedelta(days=1)
    month_str = last_day_of_prev_month.strftime("%Y-%m")
    month_label = last_day_of_prev_month.strftime("%B %Y")

    # Monthly rolls up from that month's saved Weekly reports, not raw transcripts
    all_weekly = list_files(drive, WEEKLY_REPORTS_FOLDER_ID)
    this_month_weeklies = [f for f in all_weekly if month_str in f["name"]]
    this_month_weeklies.sort(key=lambda f: f["name"])

    if not this_month_weeklies:
        print(f"No weekly reports found for {month_str} — skipping monthly report.")
        return

    parts = []
    for f in this_month_weeklies:
        content = download_bytes(drive, f["id"])
        parts.append(f"--- {f['name']} ---\n{_docx_bytes_to_text(content)}")
    source_text = "\n\n".join(parts)

    prior_reports_text = _recent_reports_text(drive, MONTHLY_REPORTS_FOLDER_ID, limit=2)

    report = generate_report(
        PROJECT_INSTRUCTIONS, "Monthly", month_label, len(this_month_weeklies),
        source_text, prior_reports_text=prior_reports_text,
    )
    docx_bytes = render_report_docx(report)
    filename = f"YLL_Ops_Report_Monthly_{month_str}.docx"

    removed = delete_files_with_prefix(drive, MONTHLY_REPORTS_FOLDER_ID, filename)
    if removed:
        print(f"Removed {removed} existing monthly report(s) for {month_str} before writing fresh one.")
    upload_docx(drive, MONTHLY_REPORTS_FOLDER_ID, filename, docx_bytes)
    send_dm_to_team(
        f"🗓️ Monthly ops report for {month_label} is attached and saved to Drive.",
        filename=filename,
        file_bytes=docx_bytes,
    )
    print(f"Monthly report for {month_str} generated, saved, and sent.")


DELIVERY_HOUR_LOCAL = 7  # 7am Eastern, year-round


def main():
    now = datetime.now(TZ)
    forced = os.environ.get("FORCE_RUN", "").lower() in ("true", "1", "yes")
    if now.hour != DELIVERY_HOUR_LOCAL and not forced:
        # The other half of the 11:00/12:00 UTC cron pair — see module docstring.
        print(f"Local time is {now:%H:%M %Z}, not {DELIVERY_HOUR_LOCAL:02d}:00 — "
              f"nothing to do. (FORCE_RUN=true to override.)")
        return

    today = now.date()
    drive = get_drive_service()

    run_daily(drive, today)

    if today.weekday() == 0:  # Monday
        run_weekly(drive, today)

    if today.day == 1:
        run_monthly(drive, today)


if __name__ == "__main__":
    main()
