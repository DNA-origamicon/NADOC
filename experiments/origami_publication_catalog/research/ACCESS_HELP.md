# Fast research access handoff

Open [the access queue](ACCESS_REQUESTS.html). Empty means no action is needed.
First apply the mandatory staple-table gate in RESEARCH_PROTOCOL.md. If no
qualifying table is found, note that and move on. Do not create access requests or
exhaust alternative retrieval routes solely to rescue a failed/unknown gate.
The access workflow below applies to remaining work on records that pass the gate,
or to sources explicitly requested/provided by the user.
The agent should exhaust reasonable public supplement, author/repository and
CU-connected browser routes before adding a request. Do not equate Cloudflare
challenges with missing institutional entitlement. Continue independent work while
requests await a response. Conference discovery remains deferred under the current
research priorities.

For a download request:

1. Open its resource link in your normal CU-connected browser. Authenticate privately
   there only if the site requires it.
2. Save the requested PDF, ZIP or XLSX to Downloads as `ACCESS-<id>.pdf` (or `.zip` or
   `.xlsx`), using the exact ID shown in the queue.
3. Tell the agent it is ready. The agent collects only exact request-ID filenames;
   it does not scan the rest of Downloads or read browser state. Alternatively,
   provide the local path to the file and the request ID.

For a question, reply in chat with the ID and answer. Never send passwords,
cookies, access tokens or browser profiles. Saved files stay local; this system
neither publishes nor uploads them. The original download is left untouched.

Agent commands, from the repository root:

```bash
python3 experiments/origami_publication_catalog/research/access_queue.py list
python3 experiments/origami_publication_catalog/research/access_queue.py render
python3 experiments/origami_publication_catalog/research/access_queue.py collect ~/Downloads
python3 experiments/origami_publication_catalog/research/access_queue.py ingest ACCESS-ID /path/to/file.pdf
python3 experiments/origami_publication_catalog/research/access_queue.py answer ACCESS-ID 'User answer'
```

Create a request with `request --doi DOI --url STABLE_PUBLIC_URL --reason REASON
--attempt ATTEMPT` (repeat `--attempt` for each attempted route); add `--kind question`
for clarification. Use only public URLs without query strings, fragments or embedded
credentials. Explain the exact resource and why intervention is necessary in chat,
and link the queue. Avoid arbitrary retry loops or asking the user for every403.

`access_requests.json` retains stable IDs, status and receipt events. Received
files are copied atomically into ignored `assets/human-assisted/`, with SHA-256,
byte count and the public source URL. A received file still needs content identity,
publication/version, source completeness and design checks before research ledger
promotion. Import validates PDF signatures or ZIP integrity, not scientific content.
Limits:100MiB per file;500MiB expanded archive. Larger/other file types require an
explicit inspected import route. Requests and imports use the campaign’s single-writer
convention; do not run multiple writers concurrently.

Successful public downloads continue through the existing paced resumable
`acquire_sources.py` and ACS supplement/restoration workflows. Never restart
successful downloads or make human assistance a prerequisite for independent work.
