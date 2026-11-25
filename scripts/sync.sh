#!/usr/bin/env bash
set -euo pipefail

for required in SPARQL_ENDPOINT SPARQL_USERNAME SPARQL_PASSWORD; do
  if [[ -z "${!required:-}" ]]; then
    printf 'Cannot synchronise RDF: missing %s.\n' "$required" >&2
    exit 1
  fi
done

uv run --locked kgm sync resources/manifest.ttl "$SPARQL_ENDPOINT" \
  --username "$SPARQL_USERNAME" --password "$SPARQL_PASSWORD" \
  True False True False
