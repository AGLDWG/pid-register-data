# Proposed ASGS Meshblock categories redirect update

The Meshblock categories scheme (`https://linked.data.gov.au/def/asgs/cat`) is now published in BDR development. Its current PID resolves to legacy GitHub-hosted ASGS files. This proposal moves the scheme and its single-segment concept IRIs to BDR production destinations, once those destinations have been verified.

**Draft only. Production verification is pending.** `asgs-cat-update.ttl` is a proposed replacement for `resources/pids/def/items/asgs.ttl`, retaining the existing ASGS registration IRI. It is outside the publication manifest; the active registration has not been edited. There is no new catalogue membership to add.

## Proposed behavior

| Request | Production destination |
| --- | --- |
| Scheme HTML | `https://resources.bdr.gov.au/catalogues/vocabs:/collections/asgs:cat` |
| Concept HTML, for example `…/cat/residential` | `https://resources.bdr.gov.au/catalogues/vocabs:/collections/asgs:cat/items/cat:residential` |
| Scheme or concept Turtle | `https://bdr.azure-api.net/prez-v4/v1/object?iri={URL-encoded requested IRI}&_mediatype=text%2Fturtle` |

The specific Meshblock rules precede the original ASGS rules. Turtle is selected by an `Accept: text/turtle` header, `_mediatype=text/turtle` (including URL-encoded slash), or a `.ttl` suffix. Other requests use HTML. Scheme trailing slashes are normalized. Namespace rules cover future single-segment slugs as well as the 16 known concepts; existence of future concepts is not asserted. Nested concept paths are outside this proposal. Routing is basic HTML/Turtle selection, not full Accept quality-value negotiation.

The original rules and four redirect tests are preserved. The original creator, sponsor, creation date, registration name and stable status are preserved; only the rules, tests and modification date change. The stable status belongs to the existing registration and does not indicate approval of this proposed update. Record creation is still attributed to Laurent Lefort and sponsorship to AGLDWG. This draft does not assert a change of registration stewardship.

## Evidence collected on 2026-10-08

- The current scheme PID returns HTTP 302 to `https://raw.githack.com/AGLDWG/asgs-ont/master/asgs-cat.ttl` for HTML, and to `https://raw.githack.com/AGLDWG/asgs-ont/master/asgs.ttl` for Turtle.
- The development HTML collection page renders the scheme and member links. Its history note says DCCEEW acquired it for BDR in September 2026 after the previous ASGS API went offline in 2025.
- The development UI exposes `https://resources-bdr-dev-prez-0zlag.azurewebsites.net` as its API base. Its OpenAPI document supports `/object`, `iri` and `_mediatype`.
- Development `/object` Turtle requests for the scheme and `residential` both return HTTP 200 and parse as RDF: respectively 46 and 6 triples, including 14 and 6 statements about the requested subject. The scheme response contains metadata and member references, not a complete vocabulary download. Other concepts have generated redirect tests but their live destination content has not been individually checked.
- The production UI exposes `https://bdr.azure-api.net/prez-v4/v1` as its API base. The proposed production HTML route returns the app shell but does not render the collection. Production `/object` requests for both sampled IRIs return HTTP 404 with an Azure Container App Unavailable page. Production API compatibility therefore remains unverified.

## Reproduce the draft

The frozen original registration comes from `AGLDWG/pid-register-data` commit `5f9a383be9747bc681360433bbe37bb33e57fdaf`, path `resources/pids/def/items/asgs.ttl`, SHA-256 `fbc953a501bf519237e28275eb4e044182deb4035cccc2290d8bd9b41c2fe6b3`.

The frozen vocabulary comes from the clean local `dcceew-bdr/resources.bdr.gov.au-data` checkout at commit `4b4b9d6223b4853d42a49d2213f0165a742873a1`, path `resources/vocabs/items/mesh-block-categories.ttl`, SHA-256 `21cc5b78a0cd6366deeac89c1fc671e5634328147f261a116668655f78915310`. These are reproducibility fixtures, not authoring masters.

From the register repository root, choose an unused output path:

```sh
uv run python examples/prepare_asgs_cat_update.py --output /tmp/asgs-cat-update.ttl
```

This writes the full proposed ASGS record and `/tmp/asgs-cat-update.preview.json`, listing 59 new redirect cases and the four preserved cases. It does not use the new-registration generator, which currently supports only top-level scheme paths. The focused update builder preserves the wider ASGS record.

```sh
kurra shacl validate /tmp/asgs-cat-update.ttl \
  resources/persons/items/laurent.lefort.ttl resources/orgs/items/agldwg.ttl \
  -s resources/validators/items/pid.ttl
uv run python -m unittest discover -s tests -v
```

On macOS, the tests use temporary loopback Apache instances. They verify all 63 record cases and compare three neighboring/out-of-scope paths against the original rules. They also check metadata preservation and byte-for-byte reproduction. Apache is stopped afterwards. On other platforms, use the existing Docker harness with Docker running:

```sh
task test-one SOURCE=/tmp/asgs-cat-update.ttl PID=/tmp/asgs-cat-update.ttl
```

These tests verify redirect status and Location, not destination availability.

## Before applying the update

When production is restored, verify that the scheme HTML page and all 16 concept HTML pages load the expected resources anonymously; verify each production Turtle response parses and describes its requested IRI. Confirm the production prefix bindings and endpoint routes match these candidates. Resolve any differences in the draft destinations first. Rebase the draft on the latest ASGS registration if that record has changed, review the update through a PR, and follow the registry's deployment process. Do not copy the development hostname into the live redirect record as a workaround for the production outage.
