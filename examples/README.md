# Local PID proposal generation

The second worked example is an [update to the existing ASGS registration for Meshblock categories](asgs-cat-update.md). Its draft and redirect tests use candidate production BDR destinations; production verification is pending.

`odrl-action-one-concept.ttl` is the annotated learning stub. `odrl-action.ttl` is the complete generated draft, and `odrl-action.preview.json` lists its expected redirects and external concepts that are excluded. These files live outside `resources/` and the publication manifest.

## Inputs

The generator needs two inputs:

- Vocabulary Turtle: the scheme, concept IRIs and membership relationships. Multiple RDF types are supported; local members must explicitly be `skos:Concept` instances.
- A JSON plan: the scheme, local namespace, registration title/description, creator, proposed sponsor, explicit dates and HTML/Turtle destination templates. Each template contains `{iri}` inside a query parameter; the generator URL-encodes that requested IRI.

The plan is `odrl-action-plan.json`. KurrawongAI is the record creator as requested; IDN is the proposed sponsor based on the vocabulary's publisher metadata, subject to registration review. The generated `submitted` status represents the proposal state only: generating it does not submit a request or certify sponsorship or approval.

`input/odrl-action.ttl` is a frozen example input copied unchanged from `idn-au/indigenous-data-catalogue` at commit `11b777dbb2b35aa757e00ad5008f897a863d25d5`, path `resources/reference/vocabs/sync/odrl-action.ttl`. Its SHA-256 is `5efe551ea21111a2b81d1826cc97b38c93f78683f36309ea65863e303fb7070a`. It is a reproducibility fixture, not the authoring master; make vocabulary changes in the IDN source repository and deliberately refresh this fixture and generated outputs when appropriate.

## Generate

From the repository root, choose an output path that does not already exist:

```sh
task generate-proposal VOCABULARY=examples/input/odrl-action.ttl PLAN=examples/odrl-action-plan.json OUTPUT=/tmp/odrl-action-proposal.ttl
```

The equivalent script command is:

```sh
uv run python scripts/generate_pid.py \
  --vocabulary examples/input/odrl-action.ttl \
  --plan examples/odrl-action-plan.json \
  --output /tmp/odrl-action-proposal.ttl
```

The second output is `/tmp/odrl-action-proposal.preview.json`. With unchanged input, plan and dependencies, repeated generation produces identical files. Dates come from the plan; the clock is not consulted. Existing outputs are never overwritten.

## Scope of the first version

- One explicitly selected scheme at `https://linked.data.gov.au/def/<slug>` and its slash namespace.
- Single-segment concept names containing letters, digits and hyphens. Hash IRIs and nested paths are rejected rather than guessed.
- Scheme membership is discovered from `skos:inScheme`, `skos:hasTopConcept` and `skos:topConceptOf`. A locally named concept missing membership causes an error.
- External members such as W3C's `odrl:transfer` are reported in the preview and receive no registration or redirect tests.
- Namespace rules cover matching single-segment child IRIs, including future terms. That is namespace coverage, not a guarantee that every possible child IRI exists.
- A Turtle `Accept` header or `_mediatype=text/turtle` selects the API destination. Other requests use the HTML destination. This is basic HTML/Turtle routing, not a complete HTTP Accept quality-value negotiator.
- A trailing slash on the scheme is normalised to the scheme IRI; a concept trailing slash is outside this initial scope.
- Each known scheme/concept has HTML and Turtle redirect tests. Additional cases exercise scheme trailing slashes and explicit format requests.
- The preview shows the catalogue membership triple to add after review. The generator does not modify catalogue files, infer authorisation, upload RDF, change approval state, commit, push or restart services.

## Validate and test

The PID validator requires the creator and sponsor's types to be present. Validate the proposal with the relevant party records:

```sh
kurra shacl validate /tmp/odrl-action-proposal.ttl \
  resources/orgs/items/kurrawong-ai.ttl resources/orgs/items/idn.ttl \
  --shacl resources/validators/items/pid.ttl
```

Run generator tests:

```sh
uv run python -m unittest discover -s tests -p test_generate_pid.py -v
```

These test repeatability across processes, external-term handling, membership omissions and invalid plans. On macOS they also run all 22 worked-example cases against a temporary loopback Apache server and check that neighbouring namespaces do not redirect. The server is stopped after testing. On other platforms that native Apache check is skipped; use the existing Docker harness below.

With Docker running, test a generated proposal through the repository's existing harness:

```sh
task test-one SOURCE=/tmp/odrl-action-proposal.ttl PID=/tmp/odrl-action-proposal.ttl
```

Redirect tests check HTTP status and `Location`, not the content or availability of the remote representation. Source validation, destination checks, sponsorship confirmation and allocation approval remain part of review before a proposal is moved into the active register.
