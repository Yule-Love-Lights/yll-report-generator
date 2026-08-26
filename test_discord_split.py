"""Discord rejects any message whose content exceeds 2000 characters with a
400. A board note built from report data has no natural length bound, and
an unsplit one took down a whole daily report on 2026-08-25. These check
split_content never emits an over-long chunk and never loses text."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DISCORD_BOT_TOKEN", "test")

from discord_dm import MAX_CONTENT, split_content  # noqa: E402

ok = True


def check(cond, msg):
    global ok
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        ok = False


def joined(chunks):
    return "\n".join(chunks)


# The real shape: many bullet lines, comfortably over the limit.
board_note = "**Task board**\n" + "\n".join(
    f"• NEW → For Naldo: task number {i} with a reasonably wordy title on it"
    for i in range(120)
)
chunks = split_content(board_note)
check(len(board_note) > MAX_CONTENT, f"fixture is over the limit ({len(board_note)} chars)")
check(len(chunks) > 1, f"it got split ({len(chunks)} messages)")
check(all(len(c) <= MAX_CONTENT for c in chunks),
      f"no chunk exceeds {MAX_CONTENT} (max was {max(len(c) for c in chunks)})")
check(joined(chunks) == board_note, "round-trips without losing or reordering text")
check(all("\n• NEW" not in c[:1] for c in chunks) and all(c for c in chunks),
      "no empty chunks emitted")

# A single line longer than the limit still has to go somewhere.
monster = "x" * (MAX_CONTENT * 2 + 17)
chunks = split_content(monster)
check(all(len(c) <= MAX_CONTENT for c in chunks), "an over-long single line is hard-split")
check("".join(chunks) == monster, "hard-split line loses nothing")

# Short and empty inputs stay simple.
check(split_content("hello") == ["hello"], "short text is one chunk, unchanged")
check(split_content("") == [], "empty text produces no chunks")
check(len(split_content("a\n" * 3000)) >= 2, "many tiny lines still split")

# Exactly at the boundary must not split.
exact = "y" * MAX_CONTENT
check(split_content(exact) == [exact], "content exactly at the limit is not split")

print("\nRESULT:", "ALL PASS" if ok else "FAILURES ABOVE")
sys.exit(0 if ok else 1)
