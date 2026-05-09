#!/usr/bin/env bash
set -euo pipefail
# typikon-defaults.sh — single source of truth for default values used
# by typikon's bin/* scripts (typikon-init, typikon-refresh, future).
#
# This file is SOURCED (not executed) by every bin/* script that needs
# a default:
#
#     # near the top of the script:
#     # shellcheck source=./typikon-defaults.sh
#     . "$(dirname "${BASH_SOURCE[0]}")/typikon-defaults.sh"
#
# The shebang is a hint to editors / linters; running the file directly
# is a no-op (it only sets variables; no top-level commands fire).
#
# Each entry is `: "${VAR:=default}"` so the existing env-var override
# semantics keep working: callers pre-set `VAR` (or pass it through from
# `TYPIKON_<VAR>`) before sourcing, and the `:=` form leaves a non-empty
# preset alone. Only set defaults here; do not run side effects.

# Pinned Zola version. Bump when typikon's Phase-5 gate validates
# against a new Zola release. Consumer-side workflows pick this up on
# their next `themes/typikon/bin/typikon-refresh` invocation.
: "${ZOLA_VERSION:=0.22.1}"
