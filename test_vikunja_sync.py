"""Offline harness for vikunja_sync: fake Drive, fake Vikunja, fake Claude.

Exercises the paths that are expensive to get wrong — exact-fingerprint
rollover, semantic rollover, creation + bucket routing + assignment,
auto-close into the Auto Closed bucket, the low-confidence gate, the daily
cap, the rerun guard, and dry run.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.update({
    "ANTHROPIC_API_KEY": "sk-test",
    "VIKUNJA_API_TOKEN": "tk_test",
    "VIKUNJA_USERNAME_JASON": "jason",
    "VIKUNJA_USERNAME_NALDO": "naldo",
    "VIKUNJA_SYNC_MAX_NEW_TASKS": "2",
})

# --- stub the two modules vikunja_sync imports before it loads -----------
fake_anthropic = types.ModuleType("anthropic")


class _FakeAnthropic:
    def __init__(self, **kw):
        self.messages = types.SimpleNamespace(create=lambda **kw: CLASSIFY_RESPONSE)


fake_anthropic.Anthropic = _FakeAnthropic
sys.modules["anthropic"] = fake_anthropic

fake_drive_helpers = types.ModuleType("drive_helpers")
DRIVE_FILES = {}


def _list_files(drive, folder_id, name_prefix=None):
    return [{"id": n, "name": n} for n in DRIVE_FILES
            if name_prefix is None or n.startswith(name_prefix)]


fake_drive_helpers.list_files = _list_files
fake_drive_helpers.download_json = lambda drive, fid: DRIVE_FILES[fid]
fake_drive_helpers.upload_json = lambda drive, folder, name, data: DRIVE_FILES.__setitem__(name, data)
fake_drive_helpers.delete_files_with_prefix = lambda drive, folder, prefix: [
    DRIVE_FILES.pop(n) for n in list(DRIVE_FILES) if n.startswith(prefix)]
fake_drive_helpers.get_drive_service = lambda: None
sys.modules["drive_helpers"] = fake_drive_helpers


class _Exec:
    def __init__(self, fn):
        self._fn = fn

    def execute(self, num_retries=0):
        return self._fn()


class FakeDrive:
    """Enough of the Drive client for _save_index, which writes the index
    file through the API directly rather than via drive_helpers."""

    @staticmethod
    def _payload(media):
        import json as _json
        return _json.loads(media.getbytes(0, media.size()).decode("utf-8"))

    def files(self):
        return self

    def update(self, fileId=None, media_body=None, supportsAllDrives=None):
        if fileId not in DRIVE_FILES:
            raise AssertionError(f"update() on unknown file {fileId}")
        return _Exec(lambda: DRIVE_FILES.__setitem__(fileId, self._payload(media_body)))

    def create(self, body=None, media_body=None, fields=None, supportsAllDrives=None):
        name = body["name"]
        return _Exec(lambda: DRIVE_FILES.__setitem__(name, self._payload(media_body)))


DRIVE = FakeDrive()

import vikunja_sync  # noqa: E402
from vikunja_client import VikunjaError  # noqa: E402

CLASSIFY_RESPONSE = None
CALLS = []


class FakeVikunja:
    """Board: task 101 open (exact-fp rollover), 102 open (semantic
    rollover), 103 open (gets auto-closed)."""

    def __init__(self, *a, **kw):
        self.next_id = 200
        self.tasks = {}

    def get_project_by_title(self, title):
        assert title == "Tasks from Reports", title
        return {"id": 7, "title": title}

    def get_kanban_view(self, pid):
        return {"id": 3, "view_kind": "kanban"}

    def get_buckets(self, pid, vid):
        return {"for jason": 11, "for naldo": 12, "for anyone": 13,
                "done": 14, "auto closed": 15}

    def get_project_users(self, pid):
        return {"jason": 1, "naldo": 2}

    def list_open_tasks(self, pid):
        fp = vikunja_sync._fingerprint("jason", "Send the Kravitz quote")
        return [
            {"id": 101, "title": "Send the Kravitz quote",
             "description": f"<p>x</p><p><code>yll-sync-id: {fp}</code></p>"},
            {"id": 102, "title": "Follow up with Palm Beach HOA", "description": ""},
            {"id": 103, "title": "Order the C9 bulbs", "description": ""},
        ]

    def create_task(self, pid, title, description="", due_date=None, priority=None):
        self.next_id += 1
        CALLS.append(("create", title, due_date, priority))
        return {"id": self.next_id, "title": title}

    def move_task_to_bucket(self, pid, vid, bucket, tid):
        CALLS.append(("move", tid, bucket))

    def assign_user(self, tid, uid):
        CALLS.append(("assign", tid, uid))

    def add_comment(self, tid, text):
        CALLS.append(("comment", tid))

    def ensure_label(self, title, hex_color="4a7c59"):
        return 99

    def add_label(self, tid, lid):
        CALLS.append(("label", tid, lid))


vikunja_sync.VikunjaClient = FakeVikunja

REPORT = {
    "master_action_list": {
        "Jason": [
            {"item": "Send the Kravitz quote", "date_raised": "2026-08-24"},          # 0 exact dup
            {"item": "Chase the HOA on the proposal", "date_raised": "2026-08-25"},   # 1 semantic dup
            {"item": "Call the Levittown lead back", "date_raised": "2026-08-25"},    # 2 new
        ],
        "Naldo": [
            {"item": "Get the van inspected", "date_raised": "2026-08-25"},           # 3 new
            {"item": "Maybe think about rebranding someday", "date_raised": "2026-08-25"},  # 4 skip
        ],
        "Both": [
            {"item": "Decide on 2027 pricing", "date_raised": "2026-08-25"},          # 5 low conf
            {"item": "Book the warehouse cleanout", "date_raised": "2026-08-25"},     # 6 over cap
        ],
    },
    "closed_since_last_report": ["Naldo said the C9 bulbs are ordered"],
}


def build_response():
    """pending indices after the exact-fp pass: the 6 non-duplicate items."""
    return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=__import__("json").dumps({
        "items": [
            {"index": 0, "verdict": "duplicate", "existing_task_id": 102,
             "title": "", "due_date": None, "priority": 0, "confidence": "high", "reason": "same HOA follow-up"},
            {"index": 1, "verdict": "new", "existing_task_id": None,
             "title": "Call the Levittown lead back", "due_date": "2026-08-27",
             "priority": 3, "confidence": "high", "reason": "new lead"},
            {"index": 2, "verdict": "new", "existing_task_id": None,
             "title": "Get the van inspected", "due_date": None,
             "priority": 1, "confidence": "high", "reason": "new"},
            {"index": 3, "verdict": "skip", "existing_task_id": None,
             "title": "", "due_date": None, "priority": 0, "confidence": "high", "reason": "musing, no action"},
            {"index": 4, "verdict": "new", "existing_task_id": None,
             "title": "Decide on 2027 pricing", "due_date": None,
             "priority": 0, "confidence": "low", "reason": "unclear if decided"},
            {"index": 5, "verdict": "new", "existing_task_id": None,
             "title": "Book the warehouse cleanout", "due_date": None,
             "priority": 0, "confidence": "high", "reason": "new"},
        ],
        "closures": [{"task_id": 103, "reason": "Naldo said the bulbs are ordered"}],
    }))])


def run(label, dry=False):
    global CLASSIFY_RESPONSE
    CALLS.clear()
    CLASSIFY_RESPONSE = build_response()
    os.environ["VIKUNJA_SYNC_DRY_RUN"] = "true" if dry else "false"
    s = vikunja_sync.sync_daily_report(DRIVE, REPORT, "2026-08-25", "state-folder")
    print(f"\n===== {label} =====")
    print(vikunja_sync.format_summary_for_discord(s))
    return s, list(CALLS)


ok = True


def check(cond, msg):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        ok = False


# 1. Dry run writes nothing
s, calls = run("DRY RUN", dry=True)
check(calls == [], "dry run made zero write calls")
check(len(s["created"]) == 2, f"dry run planned 2 creates (cap=2), got {len(s['created'])}")
check("vikunja_task_index.json" not in DRIVE_FILES, "dry run did not persist the index")

# 2. Real run
s, calls = run("REAL RUN")
created = {c["title"]: c for c in s["created"]}
check(len(s["created"]) == 2, f"created 2 (cap=2), got {len(s['created'])}")
check(created.get("Call the Levittown lead back", {}).get("bucket") == "For Jason",
      "Jason's item routed to 'For Jason'")
check(created.get("Get the van inspected", {}).get("bucket") == "For Naldo",
      "Naldo's item routed to 'For Naldo'")
check(len(s["restated"]) == 2, f"2 rollovers (1 exact + 1 semantic), got {len(s['restated'])}")
check({r["match"] for r in s["restated"]} == {"exact", "semantic"},
      "one exact-fingerprint and one semantic rollover")
check(all(("create", r["title"], None, 0) not in calls for r in s["restated"]),
      "no rollover was re-created as a new task")
check([c for c in calls if c[0] == "move" and c[2] == 15] == [("move", 103, 15)],
      "task 103 moved into the 'Auto Closed' bucket (15)")
check(("assign", 201, 1) in calls, "Jason's new task assigned to user 1")
check(("assign", 202, 2) in calls, "Naldo's new task assigned to user 2")
check(all(c[0] != "done" for c in calls), "auto-close never marks the task done")
whys = " | ".join(n["why"] for n in s["needs_review"])
check(len(s["needs_review"]) == 3, f"3 items flagged instead of written, got {len(s['needs_review'])}")
check("low confidence" in whys, "low-confidence item withheld from the board")
check("skipped" in whys, "non-actionable musing skipped")
check("cap" in whys, "over-cap item withheld and reported")
due = created.get("Call the Levittown lead back", {}).get("due_date")
check(due == "2026-08-27", f"stated due date carried through, got {due}")
check(("create", "Call the Levittown lead back", "2026-08-27T21:00:00Z", 3) in calls,
      "due date converted to RFC3339 (5pm ET -> 21:00Z) and priority passed")

# 3. Rerun guard
s2, calls2 = run("RERUN SAME DAY")
check(s2 is None, "same-date rerun is a no-op")
check(calls2 == [], "same-date rerun made zero write calls")

# 4. Missing bucket surfaces clearly
FakeVikunja.get_buckets = lambda self, p, v: {"for jason": 11, "done": 14}
DRIVE_FILES.pop("vikunja_task_index.json", None)
try:
    run("MISSING BUCKETS")
    check(False, "missing bucket raised")
except VikunjaError as e:
    check("Auto Closed" in str(e) and "For Naldo" in str(e),
          "missing buckets named explicitly in the error")



# 5. A task created but not fully decorated is still recorded, not orphaned
class FlakyVikunja(FakeVikunja):
    def move_task_to_bucket(self, pid, vid, bucket, tid):
        raise VikunjaError("connect timeout")


vikunja_sync.VikunjaClient = FlakyVikunja
DRIVE_FILES.pop("vikunja_task_index.json", None)
FakeVikunja.get_buckets = lambda self, p, v: {"for jason": 11, "for naldo": 12,
                                              "for anyone": 13, "done": 14, "auto closed": 15}
s, calls = run("BUCKET MOVE FAILS")
check(len(s["created"]) == 2, f"tasks still recorded as created, got {len(s['created'])}")
check(all(c["task_id"] for c in s["created"]), "created tasks kept their real task ids")
check(all(c.get("incomplete") for c in s["created"]), "each is flagged incomplete")
check(any("incomplete" in e for e in s["errors"]), "incompleteness surfaced as an error")
check(len(DRIVE_FILES.get("vikunja_task_index.json", {}).get("tasks", {})) >= 2,
      "fingerprints still written to the index (no orphans)")
check(any(c[0] == "assign" for c in calls) and any(c[0] == "label" for c in calls),
      "later steps still ran after the bucket move failed")

print("\nFINAL:", "ALL PASS" if ok else "FAILURES ABOVE")
sys.exit(0 if ok else 1)
