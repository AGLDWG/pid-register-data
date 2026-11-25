# Supporting vocabularies

These versioned copies provide reference types for register validation. They are dependencies, not organisation records, and are not included in the publication manifest.

`aarr.ttl` is the Indigenous Data Network Agent to Agent Relationship Roles vocabulary, version `0.0.2`, namespace `https://data.idnau.org/pid/vocab/aarr/`. It was copied unchanged on 2026-10-09 from `idn-au/agents-governance-profile`, commit `13d6dec560b54616c86646ea48253c6c90e4f004`, path `resources/aarr.ttl`:

- Source: <https://github.com/idn-au/agents-governance-profile/blob/13d6dec560b54616c86646ea48253c6c90e4f004/resources/aarr.ttl>
- SHA-256: `79d2afedc36515607d2910526cd994dace6ca1d55529413c4647057d0fc336c3`
- Its own license and attribution metadata are retained in the copied file.

The organisation validation script parses the complete vocabulary and imports its named concepts' `rdf:type skos:Concept` statements into the validation graph. It does not merge vocabulary publisher metadata into the organisation register: AARR describes IDN using a different URL, which would otherwise conflict with the register's single-URL constraint. Organisation/person types come from the register's own agent records. This validates roles as SKOS concepts; it does not require that every role used belongs specifically to AARR.

Validation runs offline. Refresh a vocabulary copy deliberately in a PR: update its source version, commit and checksum here, then rerun `task validate-orgs` and the validation tests. Do not edit the copy as the authoring master.
