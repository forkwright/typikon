#!/usr/bin/env python3
"""Structural regression guard for two-phase Typikon release workflows."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / ".github" / "workflows" / "release-please.yml"
CANDIDATE = ROOT / ".github" / "workflows" / "release-candidate.yml"
VERIFIER = ROOT / "ci" / "verify-release-lock.py"
CONSUMER = ROOT / "ci" / "github-workflow.yml.tmpl"
RELEASING = ROOT / "docs" / "RELEASING.md"


class ContractError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def action_refs(text: str) -> list[str]:
    return re.findall(r"^\s*-?\s*uses:\s+[^@\s]+@([^\s#]+)", text, re.MULTILINE)


def step_blocks(text: str) -> dict[str, str]:
    matches = list(re.finditer(r"^      - name: (.+)$", text, re.MULTILINE))
    result = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result[match.group(1)] = text[match.start() : end]
    return result


def job_block(text: str, name: str) -> str:
    match = re.search(rf"^  {re.escape(name)}:\n", text, re.MULTILINE)
    if match is None:
        return ""
    following = re.search(r"^  [A-Za-z0-9_-]+:\n", text[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(text)
    return text[match.start() : end]


def validate(release: str, candidate: str, verifier: str) -> None:
    require(
        "if: github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'"
        in release,
        "manual publisher is not bound to refs/heads/main",
    )
    require(
        "acknowledge_private_consumer_metadata:" in release
        and "default: false" in release
        and 'test "$PRIVACY_ACKNOWLEDGED" = true' in release,
        "public private-consumer metadata lacks an explicit operator acknowledgment",
    )
    require("default_branch=$(gh api" in release, "verifier does not prove default branch")
    require(
        release.count('test "$live_head" = "$GITHUB_SHA"') == 2,
        "verifier does not bind both live reads to the evidence checkout",
    )
    require(
        "skip-github-release: true" in release
        and "skip-github-release: false" not in release,
        "push preparation may create a release",
    )
    require(
        'python3 -I ci/verify-published-release.py --version "$version"' in release
        and "--jq '.draft == false' | grep -Fxq true" not in release
        and "git show-ref --verify" not in release,
        "release preparation does not verify the exact published predecessor",
    )

    verify_job = job_block(release, "verify-locked-release")
    publish_job = job_block(release, "publish-locked-release")
    require(verify_job and publish_job, "split verify/publish jobs are missing")
    verify_preamble = verify_job.split("    steps:\n", 1)[0]
    publish_preamble = publish_job.split("    steps:\n", 1)[0]
    require("contents: write" not in verify_preamble, "verifier has content-write authority")
    require("pull-requests: write" not in verify_preamble, "verifier has PR-write authority")
    require("contents: write" in publish_preamble, "publisher lacks release authority")
    require(
        "needs: verify-locked-release" in publish_preamble
        and "needs.verify-locked-release.result == 'success'" in publish_preamble,
        "publisher is not gated on the read-only verifier job",
    )
    require("    env:" not in publish_preamble, "publisher has job-global credentials")
    blocks = step_blocks(release)
    replay = blocks.get(
        "Replay candidate, artifact, consumer, workflow, and PR evidence", ""
    )
    revalidate = blocks.get("Revalidate live evidence before sealing the handoff", "")
    seal = blocks.get("Seal the verified publication handoff", "")
    handoff = blocks.get("Materialize the raw digest-bound publication handoff", "")
    publisher = blocks.get("Publish or resume the exact locked release", "")
    require(
        replay and revalidate and seal and handoff and publisher,
        "release evidence handoff steps are missing",
    )
    for secret in ("TOOLS_RECEIPT_TOKEN", "LEATHER_RECEIPT_TOKEN"):
        require(
            release.count(f"secrets.{secret}") == 2,
            f"{secret} is not scoped to two verifier steps",
        )
        require(secret in replay and secret in revalidate, f"{secret} escaped verifier steps")
        require(secret not in publish_job, f"{secret} escaped into the publisher job")
    require(
        "--materialize-candidate" in replay and "--materialize-candidate" in revalidate,
        "both live validations must materialize immutable candidate bytes",
    )
    require(
        'diff -qr "$PUBLISH_DIR" "$reverified"' in revalidate
        and 'mv "$reverified" "$PUBLISH_DIR"' in revalidate,
        "final release staging is not rebuilt and byte-compared",
    )
    second_verify = release.index(
        "      - name: Revalidate live evidence before sealing the handoff"
    )
    sealed = release.index("      - name: Seal the verified publication handoff")
    publish = release.index("      - name: Publish or resume the exact locked release")
    require(
        second_verify < sealed < publish,
        "publication handoff can precede final live verification",
    )
    require(
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
        in seal
        and "ci/materialize-release-handoff.py" in handoff
        and '--artifact-id "${{ needs.verify-locked-release.outputs.staging_artifact_id }}"'
        in handoff
        and '--artifact-digest "${{ needs.verify-locked-release.outputs.staging_artifact_digest }}"'
        in handoff
        and '--run-id "${{ needs.verify-locked-release.outputs.staging_run_id }}"'
        in handoff
        and '--run-attempt "${{ needs.verify-locked-release.outputs.staging_run_attempt }}"'
        in handoff
        and 'test "$GITHUB_RUN_ID" = "${{ needs.verify-locked-release.outputs.staging_run_id }}"'
        in handoff
        and 'test "$GITHUB_RUN_ATTEMPT" != "${{ needs.verify-locked-release.outputs.staging_run_attempt }}"'
        in handoff,
        "sealed cross-job publication handoff is not ID/digest bound",
    )
    require(
        "actions/attest-build-provenance@" not in release
        and "actions/attest-sbom@" not in release,
        "publisher regenerates attestations instead of reusing frozen candidate bundles",
    )
    require(
        "ci/publish-locked-release.py publish" in publisher
        and '--evidence-commit "${{ needs.verify-locked-release.outputs.evidence_commit }}"'
        in publisher,
        "publisher does not use the replayable evidence-bound state machine",
    )
    require(
        "$RUNNER_TEMP/release-verifier" not in publish_job
        and "pip install" not in publish_job
        and "verify-release-lock.py" not in publish_job,
        "third-party verifier dependencies escaped into the write-authorized job",
    )
    require("gh release" not in release, "workflow bypasses the publication state machine")
    require("git/refs" not in release, "workflow creates a tag outside the state machine")

    for ref in action_refs(release) + action_refs(candidate):
        require(re.fullmatch(r"[0-9a-f]{40}", ref) is not None, f"mutable action ref {ref}")
    require(
        release.count("persist-credentials: false") == 3,
        "all three release checkouts are not exactly fail-closed",
    )
    require(
        candidate.count("persist-credentials: false") == 1,
        "candidate checkout credentials are not exactly fail-closed",
    )

    require("workflow_dispatch:" not in candidate, "candidate freezer is manually writable")
    require("contents: write" not in candidate, "candidate freezer has write authority")
    require("secrets." not in candidate, "candidate freezer consumes a repository secret")
    require("freeze-candidate:" in candidate, "candidate freeze job is missing")
    require(
        'ci/build-release-candidate.py seed-sbom --output-dir "$CANDIDATE_DIR"'
        in candidate
        and "ci/build-release-candidate.py freeze" in candidate
        and "actions/upload-artifact@" in candidate,
        "candidate workflow does not seed, freeze, and upload exact bytes",
    )
    require(
        "anchore/sbom-action@" not in candidate,
        "candidate delegates SBOM generation to an unbound downloader",
    )
    candidate_order = [
        candidate.index("      - name: Generate the inventory-backed CycloneDX SBOM"),
        candidate.index("      - name: Freeze exact archive and candidate manifest"),
        candidate.index("      - name: Validate the CycloneDX schema"),
        candidate.index("      - name: Attest the frozen source archive"),
        candidate.index("      - name: Attest the frozen CycloneDX SBOM"),
        candidate.index("      - name: Freeze the offline attestation bundles"),
        candidate.index("      - name: Verify both frozen offline attestation bundles"),
        candidate.index("      - name: Upload immutable candidate bundle"),
    ]
    require(
        candidate_order == sorted(candidate_order),
        "candidate inventory, archive, validation, attestations, and upload are misordered",
    )
    require(
        "attestations: write" in candidate
        and "id-token: write" in candidate
        and "provenance.outputs.bundle-path" in candidate
        and "sbom_attestation.outputs.bundle-path" in candidate,
        "candidate workflow does not freeze both offline attestation bundles",
    )
    candidate_blocks = step_blocks(candidate)
    schema_check = candidate_blocks.get("Validate the CycloneDX schema", "")
    provenance = candidate_blocks.get("Attest the frozen source archive", "")
    sbom_attestation = candidate_blocks.get("Attest the frozen CycloneDX SBOM", "")
    attach = candidate_blocks.get("Freeze the offline attestation bundles", "")
    offline_verify = candidate_blocks.get(
        "Verify both frozen offline attestation bundles", ""
    )
    require(
        "bfc8b2538da86fe239bc53658bbb63c1c8c510a293c1e6891aa5bea5d3c58746"
        in schema_check
        and "cyclonedx-cli/releases/download/v0.33.1/cyclonedx-linux-x64"
        in schema_check
        and "sha256sum --check --strict" in schema_check
        and '"$cli" validate' in schema_check
        and "--input-format json" in schema_check
        and "--fail-on-errors" in schema_check,
        "candidate CycloneDX schema validator is not version/hash/command bound",
    )
    archive_subject = (
        "subject-path: ${{ env.CANDIDATE_DIR }}/"
        "typikon-${{ steps.detect.outputs.tag }}.tar.gz"
    )
    require(
        archive_subject in provenance
        and ".tar.gz.cdx.json" not in provenance,
        "provenance attestation does not bind the source archive",
    )
    require(
        archive_subject in sbom_attestation
        and "sbom-path: ${{ env.CANDIDATE_DIR }}/"
        "typikon-${{ steps.detect.outputs.tag }}.tar.gz.cdx.json"
        in sbom_attestation,
        "SBOM attestation does not bind the source archive and CycloneDX document",
    )
    require(
        '--provenance-bundle "${{ steps.provenance.outputs.bundle-path }}"'
        in attach
        and '--sbom-bundle "${{ steps.sbom_attestation.outputs.bundle-path }}"'
        in attach,
        "candidate finalizer does not receive both action-produced bundles",
    )
    require(
        offline_verify.count("gh attestation verify") == 2
        and '--bundle "$archive.provenance.intoto.jsonl"' in offline_verify
        and '--bundle "$archive.sbom.intoto.jsonl"' in offline_verify
        and '--signer-workflow "$signer"' in offline_verify
        and '--source-digest "$GITHUB_SHA"' in offline_verify
        and "--predicate-type https://slsa.dev/provenance/v1" in offline_verify
        and "--predicate-type https://cyclonedx.org/bom" in offline_verify,
        "candidate does not cryptographically verify both frozen offline bundles",
    )
    for suffix in (
        ".tar.gz.sha256",
        ".tar.gz.provenance.intoto.jsonl",
        ".tar.gz.sbom.intoto.jsonl",
    ):
        require(
            release.count(suffix) == 2,
            f"verifier does not stage and restage the frozen {suffix} member",
        )
    require(
        '".github/workflows/release-candidate.yml"' in verifier,
        "lock verifier names the wrong candidate workflow",
    )


def validate_consumer_receipt(template: str) -> None:
    blocks = step_blocks(template)
    record = blocks.get("Record Typikon consumer receipt", "")
    upload = blocks.get("Upload Typikon consumer receipt", "")
    require(record and upload, "consumer receipt record/upload steps are missing")
    for block in (record, upload):
        require(
            "if: github.event_name == 'pull_request'" in block,
            "consumer receipt step is not PR-only",
        )
    require(
        "themes/typikon/ci/write-consumer-receipt.py" in record
        and "--root \"$GITHUB_WORKSPACE\"" in record
        and "--output /tmp/typikon-consumer-receipt.json" in record,
        "consumer receipt writer is not bound to the hosted checkout",
    )
    require(
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in upload
        and "name: typikon-consumer-receipt-${{ github.run_id }}-${{ github.run_attempt }}"
        in upload
        and "path: /tmp/typikon-consumer-receipt.json" in upload
        and "if-no-files-found: error" in upload
        and "retention-days: 90" in upload,
        "consumer receipt artifact identity or retention drifted",
    )
    require(
        template.index("      - name: Consumer checks")
        < template.index("      - name: Record Typikon consumer receipt")
        < template.index("      - name: Upload Typikon consumer receipt")
        < template.index("      # ── Deploy on green pushes to main only"),
        "consumer receipt does not follow the exact gate and precede deployment",
    )


def validate_releasing_docs(document: str) -> None:
    signer = (
        "--signer-workflow "
        "forkwright/typikon/.github/workflows/release-candidate.yml"
    )
    require(
        document.count(signer) == 2,
        "offline verification does not bind both bundles to the candidate workflow",
    )
    require(
        document.count('--source-digest "$R"') == 2,
        "offline verification does not bind both bundles to candidate R",
    )


def reject_consumer_mutant(template: str, fragment: str) -> None:
    try:
        validate_consumer_receipt(template)
    except ContractError:
        return
    raise AssertionError(f"consumer receipt contract accepted mutant: {fragment}")


def reject_mutant(release: str, candidate: str, verifier: str, fragment: str) -> None:
    try:
        validate(release, candidate, verifier)
    except ContractError:
        return
    raise AssertionError(f"release workflow contract accepted mutant: {fragment}")


def main() -> int:
    release = RELEASE.read_text(encoding="utf-8")
    candidate = CANDIDATE.read_text(encoding="utf-8")
    verifier = VERIFIER.read_text(encoding="utf-8")
    consumer = CONSUMER.read_text(encoding="utf-8")
    releasing = RELEASING.read_text(encoding="utf-8")
    validate(release, candidate, verifier)
    validate_consumer_receipt(consumer)
    validate_releasing_docs(releasing)

    reject_mutant(
        release.replace(" && github.ref == 'refs/heads/main'", "", 1),
        candidate,
        verifier,
        "branch-dispatch publisher",
    )
    reject_mutant(
        release.replace('test "$PRIVACY_ACKNOWLEDGED" = true', "true", 1),
        candidate,
        verifier,
        "private-consumer metadata published without acknowledgment",
    )
    release_prefix, release_publish_job = release.split(
        "  publish-locked-release:\n", 1
    )
    reject_mutant(
        release_prefix
        + "  publish-locked-release:\n"
        + release_publish_job.replace(
            "    steps:\n",
            "    env:\n      LEATHER_RECEIPT_TOKEN: leak\n    steps:\n",
            1,
        ),
        candidate,
        verifier,
        "job-global private token",
    )
    reject_mutant(
        release.replace("skip-github-release: true", "skip-github-release: false", 1),
        candidate,
        verifier,
        "push can release",
    )
    reject_mutant(
        release.replace(
            'python3 -I ci/verify-published-release.py --version "$version"',
            "true # published-state check removed",
            1,
        ),
        candidate,
        verifier,
        "tag-only state can advance Release Please",
    )
    reject_mutant(
        release.replace('diff -qr "$PUBLISH_DIR" "$reverified"', "true", 1),
        candidate,
        verifier,
        "staged bytes may mutate after verification",
    )
    reject_mutant(
        release,
        candidate.replace(
            "            --provenance-bundle \"${{ steps.provenance.outputs.bundle-path }}\" \\\n",
            "",
            1,
        ),
        verifier,
        "offline provenance bundle is not frozen",
    )
    candidate_blocks = step_blocks(candidate)
    schema_block = candidate_blocks["Validate the CycloneDX schema"]
    reject_mutant(
        release,
        candidate.replace(schema_block, schema_block.split("        run:", 1)[0] + "        run: true\n", 1),
        verifier,
        "CycloneDX schema validation removed",
    )
    reject_mutant(
        release,
        candidate.replace("sha256sum --check --strict", "true", 1),
        verifier,
        "CycloneDX CLI digest not checked",
    )
    reject_mutant(
        release,
        candidate.replace(
            "subject-path: ${{ env.CANDIDATE_DIR }}/typikon-${{ steps.detect.outputs.tag }}.tar.gz",
            "subject-path: ${{ env.CANDIDATE_DIR }}/typikon-${{ steps.detect.outputs.tag }}.tar.gz.cdx.json",
            1,
        ),
        verifier,
        "provenance attests the SBOM instead of the archive",
    )
    reject_mutant(
        release,
        candidate.replace("gh attestation verify", "true # removed", 1),
        verifier,
        "offline provenance bundle is not cryptographically verified",
    )
    reject_mutant(
        release,
        candidate.replace(
            "--predicate-type https://cyclonedx.org/bom",
            "--predicate-type https://slsa.dev/provenance/v1",
            1,
        ),
        verifier,
        "offline SBOM bundle predicate is not enforced",
    )
    reject_mutant(
        release.replace("16a9c90856f42705d54a6fda1823352bdc62cf38", "v4", 1),
        candidate,
        verifier,
        "mutable action pin",
    )
    reject_mutant(
        release,
        candidate.replace("contents: read", "contents: write", 1),
        verifier,
        "candidate has write authority",
    )
    reject_mutant(
        release,
        candidate,
        verifier.replace("release-candidate.yml", "release-please.yml", 1),
        "verifier accepts the mixed preparation run",
    )
    reject_consumer_mutant(
        consumer.replace("      - name: Record Typikon consumer receipt", "      - name: Removed receipt", 1),
        "record step removed",
    )
    reject_consumer_mutant(
        consumer.replace("if: github.event_name == 'pull_request'", "if: always()", 1),
        "receipt writer not PR-only",
    )
    reject_consumer_mutant(
        consumer.replace("043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", "v7", 1),
        "receipt uploader mutable",
    )
    for fragment in (
        "--signer-workflow "
        "forkwright/typikon/.github/workflows/release-candidate.yml",
        '--source-digest "$R"',
    ):
        try:
            validate_releasing_docs(releasing.replace(fragment, "removed", 1))
        except ContractError:
            pass
        else:
            raise AssertionError(
                f"offline release documentation accepted missing binding: {fragment}"
            )

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ContractError("PyYAML is required for fail-closed workflow parsing") from exc
    yaml.load(release, Loader=yaml.BaseLoader)
    yaml.load(candidate, Loader=yaml.BaseLoader)

    for script in (
        VERIFIER,
        ROOT / "ci" / "publish-locked-release.py",
        ROOT / "ci" / "verify-published-release.py",
    ):
        result = subprocess.run(
            [sys.executable, "-I", str(script), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        require(
            result.returncode == 0,
            f"{script.name} cannot start under workflow isolation: {result.stderr}",
        )

    print("check-release-workflows: ok (authority, evidence, and phase mutants rejected)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
