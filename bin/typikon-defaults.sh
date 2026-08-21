#!/usr/bin/env bash
set -euo pipefail
# typikon-defaults.sh — resolve pinned tool versions for bin/* scripts.
#
# This file is SOURCED (not executed) by every bin/* script that needs one:
#
#     # shellcheck source=./typikon-defaults.sh
#     . "$(dirname "${BASH_SOURCE[0]}")/typikon-defaults.sh"
#
# The values are NOT written here. ci/tool-lock.toml is the single place a
# tool's version and its integrity value are recorded, and this file reads
# them (forkwright/typikon#58). Before, the version lived here and the
# checksum lived in three templates, so bumping one and not the others was a
# single forgetful edit away, and nothing in the repository would notice.
#
# WHY an override that changes a version is REFUSED rather than honoured:
# TYPIKON_ZOLA_VERSION used to change the download URL while leaving the
# checksum untouched, which is a guaranteed failed install at best and, if
# someone then "fixed" the mismatch by hand, a checksum that no longer
# describes what it guards. An environment variable cannot carry the matching
# hash, so the honest response is to send the caller to the one file where
# both live together.

_TYPIKON_BIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_TYPIKON_LOCK_READER="${_TYPIKON_BIN_DIR}/../ci/toollock.py"

_typikon_pin() {
    # _typikon_pin VAR_NAME PLACEHOLDER OVERRIDE_ENV_NAME
    local var="$1" placeholder="$2" override_name="$3"
    local locked preset
    if ! locked="$(python3 "$_TYPIKON_LOCK_READER" --get "$placeholder")"; then
        echo "typikon-defaults: cannot read ${placeholder} from ci/tool-lock.toml" >&2
        return 1
    fi
    preset="${!var:-}"
    if [[ -n "$preset" && "$preset" != "$locked" ]]; then
        {
            echo "typikon-defaults: ${override_name}=${preset} disagrees with ci/tool-lock.toml (${locked})."
            echo "  A version override cannot carry the matching integrity value, so honouring it"
            echo "  would pair a new release with the old checksum. Edit ci/tool-lock.toml instead,"
            echo "  changing version and sha256 together, then prove the pair with:"
            echo "    python3 ci/render-template.py --verify-upstream"
        } >&2
        return 1
    fi
    printf -v "$var" '%s' "$locked"
    export "${var?}"
}

# WARNING: the `|| return 1` is load-bearing and is not defensive noise.
# `set -e` does not abort on a command whose status is consumed by a control
# construct, and a bare call here leaves the NEXT pin free to run and succeed —
# so a refused override was swallowed and this file returned 0, which is the
# precise shape of a guard that reports a failure while permitting the thing it
# refused. `return` is correct because every caller SOURCES this file, and a
# sourced file returning nonzero aborts a `set -e` caller at the `.` line.
_typikon_pin ZOLA_VERSION ZOLA_VERSION TYPIKON_ZOLA_VERSION || return 1
_typikon_pin WRANGLER_VERSION WRANGLER_VERSION TYPIKON_WRANGLER_VERSION || return 1
