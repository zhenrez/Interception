"""Per-project, revisioned owner brief and conversational execution handoff.

This stores instructions, not an autonomous executor or a claim of task completion.
"""

from .files import dumps, loads


def _table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS project_briefs (
        revision INTEGER PRIMARY KEY, body TEXT NOT NULL)""")


def load(bridge):
    with bridge.connection() as db:
        _table(db)
        row = db.execute(
            "SELECT body FROM project_briefs ORDER BY revision DESC LIMIT 1"
        ).fetchone()
    return loads(row[0]) if row else None


def save(bridge, *, goal, guidelines="", constraints="", done_when="", expected_revision=0):
    fields = dict(goal=goal, guidelines=guidelines, constraints=constraints, done_when=done_when)
    if any(not isinstance(value, str) for value in fields.values()) or not goal.strip():
        raise ValueError("Enter a goal; all brief fields must be text")
    if len(dumps(fields).encode("utf-8")) > 128 * 1024:
        raise ValueError("Brief exceeds 128 KiB")
    with bridge.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        _table(db)
        revision = db.execute("SELECT COALESCE(MAX(revision), 0) FROM project_briefs").fetchone()[0]
        if revision != expected_revision:
            raise ValueError("The brief changed in another window. Reload it before saving.")
        body = dict(fields, revision=revision + 1, project_root=str(bridge.root))
        db.execute("INSERT INTO project_briefs VALUES (?, ?)", (revision + 1, dumps(body)))
    return body


def handoff(bridge):
    body = load(bridge)
    if body is None:
        raise ValueError("Save this project's goal first")
    return (
        """# Work on this project

The owner brief below is the user's goal, not proof of repository state.
Use the connected repository or ask for its location if the local path is inaccessible.
Keep work, authority, inference requests and evidence scoped to this project.

## Procedure
1. Recover current authoritative instructions, corrections, branch, uncommitted work,
   decisions and acceptance evidence. Distinguish confirmed, superseded, inferred and
   not retrieved. Do not reconstruct missing decisions from guesswork.
2. Establish the goal, guidelines, hard constraints and observable acceptance criteria.
   If 'done_when' is empty, derive criteria from the goal and available authority;
   ask only about a material unresolved decision. Never turn planning into permission
   to implement when the owner has limited the scope to planning.
3. Select the next bounded step that advances the goal. State its scope and verification.
   Reuse the existing implementation, launcher and architecture where they fit.
   Keep other projects separate. Do not replace an elected architecture for convenience.
4. Execute authorized work, verify actual behavior, and repair failures within scope.
   When inference is needed, use Interception's configured adapter. Unconnected
   inference is a blocker to report, not permission to invent a result or paid fallback.
5. Record what changed, exact revision, verification commands/results, unresolved
   blockers and the next step in the project's existing checkpoint convention.
   Do not create a second competing source of truth. Continue authorized work until
   its acceptance criteria are met or a concrete external blocker prevents progress.
6. Report concise results. Separate implemented, tested and independently accepted.
   A completed inference request is not a completed project. Ask the owner only for
   missing access or decisions that materially affect scope, safety or correctness.

## Owner brief (JSON; preserve wording)
```json
"""
        + dumps(body)
        + "\n```\n"
    )
