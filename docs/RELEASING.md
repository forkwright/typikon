# Releasing Typikon

Typikon separates release preparation, candidate freezing, consumer evidence,
and publication. A green theme gate does not by itself authorize a tag.

Publication was previously blocked by forkwright/typikon#58, which has landed:
`release/components.json` now covers every tool declared in
`ci/tool-lock.toml`, including the transitive dependencies of the shipped
`bin/` and `ci/` surfaces. The candidate builder enforces that completeness —
`ci/build-release-candidate.py` refuses to freeze a release whose inventory
omits a locked tool, and `ci/check-release-candidate.py` is the fixture that
locks the refusal in.

## Subjects

- `R` is the one-parent Release Please squash commit. Its diff contains only
  `CHANGELOG.md` and `.release-please-manifest.json`. The version tag targets
  this exact commit.
- The Release Candidate workflow builds the source archive, matching
  `sha256sum` record, inventory-backed CycloneDX SBOM, and two offline Sigstore
  bundles once from `R`. Its immutable artifact records the run, commit, tree,
  byte counts, and SHA-256 digests.
- Tools and Leather each pin `R` as `themes/typikon`, pass their hosted PR gate,
  and upload a receipt for the exact synthetic merge checkout and workflow.
- `E` is a later evidence-only commit. Relative to `R`, it may add exactly one
  compatibility lock and the two tracked receipt files. The verifier and
  publisher bytes therefore remain the versions already present in `R`.

The lock types both directions. Promotion records each consumer's gitlink to
`R`; rollback records the distinct gitlink commit and tree from that consumer's
exact PR base. The two consumers need not share a prior Typikon pin.

## Credentials

Publication needs two fine-grained, read-only repository tokens because a
repository-scoped `GITHUB_TOKEN` cannot download another repository's Actions
artifact and the two consumers have different resource owners.

- `TOOLS_RECEIPT_TOKEN`: access only to
  `ardent-tools/ardent-tools-site`, with Actions, Contents, and Pull requests
  set to read.
- `LEATHER_RECEIPT_TOKEN`: access only to `forkwright/ardent-site`, with the
  same three read permissions.

The workflow exposes these secrets only to the two verifier steps. Candidate
freezing, checkout, attestation, and publication do not receive them. Creating
or changing either repository secret is an operator-owned credential action.
The Python release clients wrap each environment token before passing it to a
network helper and expose it only while constructing the Authorization header.
Python cannot guarantee memory zeroization, so this boundary prevents accidental
logging without claiming a runtime guarantee the language cannot provide.

## Public evidence boundary

The compatibility lock and both receipts are public release assets. They name
the Leather repository and disclose its selected PR number, commit and tree
identities, workflow path and blob, run and artifact identifiers, and digests.
They do not contain source content or credentials. Because Leather is private,
publishing that metadata is a separate operator privacy decision. A successful
verifier does not grant it implicitly.

The manual dispatch requires
`acknowledge_private_consumer_metadata=true`. That run-scoped input records the
operator's decision at the publication boundary. Its default is false.

## Sequence

1. Merge release-control changes while the manifest version has an exact
   published release. The PR-only Release Please action refreshes the pending
   release PR.
2. Squash that release PR. The resulting `R` remains untagged. The preparation
   workflow parks while the manifest version lacks its tag.
3. Require the Release Candidate run on `R` to finish successfully and retain
   its exact artifact identity.
4. Pin both consumer PRs to `R`, run their hosted gates, and retain the exact
   receipt artifacts.
5. Add the lock and two byte-identical receipts in evidence commit `E`. Review
   the per-consumer promotion and rollback subjects.
6. Install the two read-only secrets only with operator approval, then dispatch
   Release Please from the current `main` head with the tracked lock path. Keep
   a reviewed single-writer hold on `main` through terminal release readback.
   Separate GitHub REST writes cannot atomically bind a branch head and release
   publication.
7. The workflow verifies the lock twice, rebuilds the nine-file staged set,
   seals it as a raw-digest-bound same-run handoff, and publishes through a
   fail-closed state machine. It creates an annotated tag at `R` whose message
   carries the lock digest, reconciles a draft and nine exact assets, then
   publishes only after byte readback. The candidate workflow freezes the two
   attestation bundles. Publication never regenerates them.
8. Verify the public annotated tag, release assets, attestations, and consumer
   repins before merging or deploying either consumer.

An ordinary interruption while `E` is still current may leave an exact tag,
draft, or partial draft asset set. Rerun the complete workflow so the read-only
verifier executes again. The workflow rejects publisher-only failed-job
reruns. The publisher accepts only an exact prior state and removes only a
same-name GitHub `starter` upload residue.

GitHub exposes annotated-tag object and ref creation as separate REST writes.
If `main` moves across that boundary, the run stops and may leave an exact
provisional tag, or a private exact draft after a later interruption. Stale-`E`
publication remains blocked. Release Please also remains parked because it
requires a published release. A tag alone does not satisfy that check. Do not
restore an old main tip or delete/recreate evidence.

GitHub offers no branch compare-and-publish transaction for the final
draft-to-public request. The publisher detects movement after exact release
readback and withholds a green receipt, but the exact release is already public.
This limitation requires the single-writer hold even though the publisher
revalidates every API state.

Resolving a provisional tag, draft, or unreceipted public release is a separate
destructive recovery action that needs exact-state cross-validation. A
conflicting tag, release, or asset always fails closed.

## Offline verification

After downloading all release assets, verify the distribution checksum and
both frozen bundles without relying on GitHub's release page:

```sh
sha256sum --check --strict typikon-v0.6.0.tar.gz.sha256
R=$(python3 -c 'import json; print(json.load(open("candidate.json"))["release"]["candidate_commit"])')
gh attestation verify typikon-v0.6.0.tar.gz \
  --bundle typikon-v0.6.0.tar.gz.provenance.intoto.jsonl \
  --repo forkwright/typikon \
  --signer-workflow forkwright/typikon/.github/workflows/release-candidate.yml \
  --source-digest "$R" \
  --predicate-type https://slsa.dev/provenance/v1
gh attestation verify typikon-v0.6.0.tar.gz \
  --bundle typikon-v0.6.0.tar.gz.sbom.intoto.jsonl \
  --repo forkwright/typikon \
  --signer-workflow forkwright/typikon/.github/workflows/release-candidate.yml \
  --source-digest "$R" \
  --predicate-type https://cyclonedx.org/bom
```

Require the compatibility lock to name the same `R` before running either
command.

This is the first typed two-consumer promotion and rollback increment for
forkwright/typikon#70. It does not claim the issue's later generalized release
bundle, provider adapter, or automatic Kanon merge refusal work is complete.
