#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SPARQL_ENDPOINT:-}" || -z "${SPARQL_USERNAME:-}" || -z "${SPARQL_PASSWORD:-}" ]]; then
  sync_env_file="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/.env"
  if [[ -f "$sync_env_file" ]]; then
    saved_sparql_endpoint="${SPARQL_ENDPOINT:-}"
    saved_sparql_username="${SPARQL_USERNAME:-}"
    saved_sparql_password="${SPARQL_PASSWORD:-}"
    set -a
    source "$sync_env_file"
    set +a
    export SPARQL_ENDPOINT="${saved_sparql_endpoint:-${SPARQL_ENDPOINT:-}}"
    export SPARQL_USERNAME="${saved_sparql_username:-${SPARQL_USERNAME:-}}"
    export SPARQL_PASSWORD="${saved_sparql_password:-${SPARQL_PASSWORD:-}}"
  fi
fi

for required in SPARQL_ENDPOINT SPARQL_USERNAME SPARQL_PASSWORD; do
  if [[ -z "${!required:-}" ]]; then
    printf 'Cannot synchronise RDF: missing %s in the environment and local .env file.\n' "$required" >&2
    exit 1
  fi
done

uv run --locked kgm sync resources/manifest.ttl "$SPARQL_ENDPOINT" \
  --username "$SPARQL_USERNAME" --password "$SPARQL_PASSWORD" \
  True False True False
