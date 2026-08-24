"""Calls Claude to turn raw transcript text (plus prior reports for
continuity) into the structured report JSON that docx_renderer builds on."""
import json
import os
from anthropic import Anthropic

MODEL = "claude-sonnet-4-6"  # update here if you want a different model

JSON_SCHEMA_INSTRUCTIONS = """
Respond with ONLY a single JSON object, no preamble, no markdown fences,
matching exactly this shape:

{
  "report_type": "Daily" | "Weekly" | "Monthly",
  "date_range": "human-readable date range string",
  "session_count": <integer>,
  "data_quality_note": "short note if source data was notably degraded, else empty string",
  "master_action_list": {
    "Naldo": [{"item": "...", "date_raised": "...", "age_note": "... or omit"}],
    "Jason": [...],
    "Both": [...],
    "TJ_Social": [...]
  },
  "closed_since_last_report": ["...", ...],
  "notable_numbers": ["...", ...],
  "decisions_notes": ["...", ...],
  "conversations_to_have": ["...", ...],
  "day_by_day": [
    {
      "date": "Weekday, Month Day",
      "sessions": <integer>,
      "action_items": ["...", ...],
      "decisions_notes": ["...", ...],
      "meetings": [{"title": "...", "notes": ["...", ...]}]
    }
  ]
}

"day_by_day" should be omitted (empty array) for Monthly reports — monthly
stays at rollup/summary level only, per project instructions.
Never invent action items, numbers, or decisions not actually supported by
the source text. If something is garbled or ambiguous, say so in an
age_note or in data_quality_note rather than guessing.
"""


def generate_report(project_instructions: str, report_type: str, date_range: str,
                     session_count: int, source_text: str, prior_reports_text: str = "") -> dict:
    client = Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

    # Daily reports are short; Weekly/Monthly synthesize much more source
    # material (especially early on, before enough daily-state history has
    # built up and raw transcripts get used as a fallback) and need more
    # room to avoid truncating mid-JSON.
    max_tokens_by_type = {"Daily": 8000, "Weekly": 16000, "Monthly": 16000}
    max_tokens = max_tokens_by_type.get(report_type, 8000)

    system_prompt = f"""{project_instructions}

{JSON_SCHEMA_INSTRUCTIONS}

You are generating a {report_type} report covering: {date_range}.
Known session count for this period: {session_count}.
"""

    user_content = f"=== RAW SOURCE TRANSCRIPTS FOR THIS PERIOD ===\n\n{source_text}"
    if prior_reports_text:
        user_content += (
            f"\n\n=== PRIOR REPORT(S) FOR CONTINUITY (use these to track "
            f"aging/open items and what has closed since) ===\n\n{prior_reports_text}"
        )

    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )

    raw_text = "".join(block.text for block in response.content if block.type == "text")
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        stop_reason = response.stop_reason
        raise RuntimeError(
            f"Claude's response wasn't valid JSON (likely truncated). "
            f"stop_reason={stop_reason}, response length={len(raw_text)} chars, "
            f"max_tokens was {max_tokens}. Original error: {e}"
        ) from e
    data.setdefault("report_type", report_type)
    data.setdefault("date_range", date_range)
    data.setdefault("session_count", session_count)
    return data
