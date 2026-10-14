#!/bin/bash
# Stage one role's pinned archive; agent is the safe default.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
role="agent"
destination=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --role) role="${2:?missing role}"; shift 2 ;;
    --destination) destination="${2:?missing destination}"; shift 2 ;;
    *) echo "unknown setup option: $1" >&2; exit 2 ;;
  esac
done

cache_root="${BPB_CACHE_ROOT:-${XDG_CACHE_HOME:-$HOME/.cache}/brainpilot-bench}"
case "$role" in
  agent)
    sha="45f8b641dac566e6ed1ba52b531a87d65400addc44ce4163f4f63df34d5933cc"
    archive="${BPB_BRAIN_AGE_AGENT_ARCHIVE:-$cache_root/$sha/data}"
    destination="${destination:-$PWD/public_data}"
    if [ -n "${BPB_BRAIN_AGE_EVALUATOR_DIR:-}" ] || [ -n "${BPB_BRAIN_AGE_EVALUATOR_ARCHIVE:-}" ]; then
      echo "evaluator data environment is present during agent setup" >&2; exit 2
    fi
    ;;
  evaluator)
    sha="08c908acef3fd26ea3efe59b4a0eaeb7c12f1c15d3c3f1b3a617b9fdecfd3c62"
    archive="${BPB_BRAIN_AGE_EVALUATOR_ARCHIVE:-$cache_root/$sha/data}"
    destination="${destination:-${BPB_BRAIN_AGE_EVALUATOR_DIR:-}}"
    if [ -z "$destination" ]; then echo "evaluator setup requires --destination or BPB_BRAIN_AGE_EVALUATOR_DIR" >&2; exit 2; fi
    if [ -n "${BPB_WORKSPACE:-}" ]; then
      case "$(cd "$(dirname "$destination")" && pwd -P)/$(basename "$destination")" in
        "$BPB_WORKSPACE"|"$BPB_WORKSPACE"/*) echo "evaluator data must be outside the agent workspace" >&2; exit 2 ;;
      esac
    fi
    ;;
  *) echo "unknown role: $role" >&2; exit 2 ;;
esac

if [ ! -f "$archive" ]; then
  echo "archive not found: $archive; use bp-bench fetch brain-age-mri --$([ "$role" = agent ] && echo public || echo private) or an explicit archive variable" >&2
  exit 1
fi
python_bin="${BPB_BRAIN_AGE_PYTHON:-python3}"
exec "$python_bin" "$script_dir/safe_unpack.py" --archive "$archive" --destination "$destination" --role "$role"
