---
name: feedback-concurrent-sessions
description: "Multiple Claude sessions run against the NADOC working tree at once — never run destructive git commands, and snapshot before bulk file rewrites."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 1300d096-e1e1-4af0-8ed5-0eaf2794062f
---

The user routinely has **more than one Claude Code session working in `/home/joshua/NADOC` at the same time**.
On 2026-07-09 a second session ran `git stash` mid-task; it reverted every uncommitted tracked file — the
user's in-progress cluster copy/paste feature and another session's doc edits — then later popped it. Nothing
was lost, but only because a snapshot had been taken first.

**Why:** the working tree is shared mutable state that no single session owns. `git stash` / `git reset` /
`git checkout -- <path>` / `git restore` operate on the *whole tree*, so they silently clobber work that a
concurrent session is mid-way through writing. A file reverting under you is a symptom of this, not a bug in
your own edits.

**How to apply:**
- Never run `git stash`, `git reset`, `git checkout -- <path>`, or `git restore` here without asking, even to
  "compare against the original". Read the file from disk instead.
- **Explicitly forbid git commands in every subagent prompt** that touches repo files — subagents reach for
  `git stash`/`git show HEAD:file` to recover an "original" and will trip this.
- Before any bulk rewrite of tracked files, copy the originals to the scratchpad. `git` is not a safe backup
  when another session may stash.
- If a file you just wrote reverts to its committed state, suspect the other session before suspecting
  yourself: check `git stash list` and `git reflog` rather than re-applying the edit blindly.
- Uncommitted work in `git status` may belong to the *other* session. Never assume dirty files are yours.

Related: [[project-context-economy-split]]
