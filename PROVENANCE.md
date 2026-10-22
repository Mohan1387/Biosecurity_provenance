# Signed provenance

Logger, Profiler, Detector and Clusterer sign receipts using separate Ed25519
keys. SHA-256 hashes bind inputs and outputs. Consumers verify signatures,
producer identity, subject identity, parent receipt hashes, and the actual input
record before analysis. Invalid or missing evidence raises HTTP 409 and writes an
`integrity_failure` audit event. Keys never enter chat prompts or tool results.

## Setup

Install `backend/requirements.txt`. Provision keys once, outside the repository:

```sh
cd backend
python provenance_keys.py /secure/tcp-keys
```

The command refuses an existing directory and prints configuration paths, not
private keys. Put the five printed `PROVENANCE_*` settings into the root `.env`
or your service environment. The registry is a public-key JSON file; deploy it
read-only from trusted operator configuration, independently of SQLite. Mount
private PEM files as secrets. Do not commit keys, copy them into container images,
or accept registry/public-key values supplied with a receipt.

Normal backend startup adds the new `provenance_receipts` table with `create_all`.
No existing tables are altered and no existing records are signed retroactively.
The backend container no longer reseeds at startup, preserving signed history
across restarts. Provision accounts explicitly on a fresh deployment.
Missing key configuration permits read-only/auth operations but blocks signed
writes and verification. There is no automatic key generation at startup.

Existing unsigned records remain in place and fail verification. For a demo,
configure a **new database** using `DATABASE_URL` and run `python seed.py`.
The seed creates fixed account/ORCID assignments and signed synthetic queries,
but no publications or profiles. Profiler must fetch public works for those
hardcoded IDs before Detector can compare publication topics. Without a profile,
Detector can still use verified queries and the declared interest alone, and its
signed decision records that no profile was available. Clusterer can
analyze the signed query activity offline. Seed receipts explicitly label their
synthetic source. The script
refuses to run if any users already exist, so it cannot replace existing activity.
Neither an ORCID ID in the seed nor a Profiler fetch verifies that the synthetic
account belongs to the real researcher.

For a local demo, from `backend/` use the same database URL for seeding and
starting the API:

```sh
export DATABASE_URL=sqlite+aiosqlite:///./tcp_orcid_provenance.db
python seed.py
uvicorn app.main:app --port 8001
```

The seed script now honors `DATABASE_URL`. With that relative URL, the new file
is `backend/tcp_orcid_provenance.db`; the existing `backend/tcp.db` is untouched.
Do not run `seed.py` a second time against the same database: it will refuse
an existing user database. Use a separate new file for another demonstration.
Run `python check_provenance.py` from `backend/` to verify every signed query,
access record, publication, profile, and warning in the configured database.
Use the restricted Profiler `/fetch-all` endpoint (or `/fetch/{user_id}`) to
populate signed ORCID-derived profiles. A failed lookup does not create a profile;
a successful lookup with no public works creates an empty signed profile, and
Detector uses only the declared-interest check in that case.
In the UI, an admin can select an account under **Admin → Prompt History** and
click **Fetch public ORCID works for this user**. This fetch is optional for
the demo scan. The all-users scan continues through accounts without fetched
profiles; it never substitutes a synthetic publication baseline. Any profile
that does exist must pass provenance verification before Detector uses it.

## Evidence and verification

Receipts contain schema version, unique receipt ID, component, key ID, subject
type/ID, issuance time, input/output snapshots and SHA-256 hashes, processing
version/parameters, and parent receipt references with hashes. Receipts and
database outputs are committed in the same transaction. Old receipts are retained
when a profile is refreshed. Profiler signs parsed publication records and binds
them into a versioned profile receipt; it attests its observation of ORCID data,
not an ORCID signature or verified researcher ownership of the ORCID identifier.

Detector requires verified Logger records and verifies any Profiler record it
uses for users with enough queries to scan. A profile's age is a separate freshness policy:
the existing 30-day refresh cache remains in use; old signatures do not expire
merely because their data is old. Research interests and Clusterer user metadata
are captured database observations, not independently authenticated claims.
Both warnings and successful no-warning decisions are signed. Review status,
reviewer and review time are mutable workflow metadata excluded from the warning
payload; changing them does not invalidate the signed original finding.

Clusterer runs in a worker thread using verified in-memory inputs and the configured
application database. Saved results use `backend/output/clusterer/<run-id>/` so
one run cannot overwrite another. A signed manifest includes exact file-byte
hashes and a `receipt.json` accompanies the artifacts. Files from a failed run
may remain but have no committed verified run; consumers must verify before use.

Restricted-user endpoints under `/api/v1/admin/provenance`:

- `GET /receipts?subject_type=...&subject_id=...`: locate receipt versions.
- `GET /receipts/{receipt_id}/verify`: recursively verify historical snapshots;
  return the receipt and complete supporting evidence chain.
- `GET /records/{subject_type}/{subject_id}/verify`: additionally compare a live
  query, access log, profile or warning with its most recent receipt.
- `GET /runs/{run_id}/verify`: verify a Clusterer run and its saved file hashes;
  return the verified result used by the dashboard.

Dashboard warnings without receipts are labeled as unsigned and shown read-only;
other verification failures block their display and review. Clusterer results
are displayed only after verification. Clearing chat does not remove
Logger evidence. Evidence includes potentially sensitive query and publication
data and is exposed only through restricted routes.

## Trust, rotation and limits

Each registry key has `component`, `public_key` (base64 raw Ed25519 public bytes),
and `status` (`active`, `retired`, `revoked`). `active` maps components to the key
ID used for new signatures. To rotate, provision a new key set in a new protected
directory, merge the desired public entries into the trusted registry, mark the
previous keys retired, update the active IDs and private-key paths, then restart
the backend. Keep retired public keys to verify old receipts. Revoked keys fail
verification for all receipts; there is no backdated grandfathering based on a
signer's claimed timestamp. Back up keys and registry securely before rotation.

This monolith remains **one signing security boundary**: code execution inside
the backend can access all four private keys. Separate identities provide
attribution, but component compromise isolation requires separate authenticated
workers with per-service secret mounts or KMS permissions. Private keys must not
be made available to LLM execution. The registry and host are trusted.

Signatures prove attribution and detect changed signed evidence, not correctness,
completeness, or freshness. SQLite receipt snapshots preserve historical evidence
but do not prevent an administrator from deleting or rolling back the entire
database. External append-only storage/checkpoints are required for rollback and
omission detection. Receipt issuance times are not independently timestamped.

Protocol v1 signs compact UTF-8 JSON with sorted keys, unescaped Unicode, finite
JSON numbers, and UTC microsecond ISO timestamps. No Unicode normalization is
performed. This is TCP's Python serialization protocol, not RFC 8785; other
implementations must reproduce its bytes exactly. Signatures cover the payload;
parent hashes cover complete envelopes. Verification has a 32-level depth limit.

## Tests

```sh
cd backend
python -m pip install pytest pytest-asyncio
python -m pytest tests -q
```

Tests use ephemeral keys, mocked ORCID responses and isolated databases. They
exercise tampering, wrong signers, unsigned inputs, rotation status, transaction
rollback, historical profile chains and artifact changes without external API
calls or altering the bundled database.
