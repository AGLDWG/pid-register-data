"""Check that stable registered PID URLs ultimately return HTTP 200 from linked.data.gov.au.

Run with ``uv run python scripts/test_resolution.py``. Requests use GET without
an Accept header and follow redirects. HTTP 403 responses are retried once with
a browser User-Agent. Exit status is 1 for resolution failures
and 2 for invalid input; this script does not require pytest or Docker.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from rdflib import Graph, Namespace, URIRef
from rdflib.exceptions import ParserError
from rdflib.namespace import RDF
from rich.console import Console
from rich.table import Table

PID = Namespace("https://linked.data.gov.au/def/pid/")
SCHEMA = Namespace("https://schema.org/")
STABLE = URIRef("https://linked.data.gov.au/def/reg-statuses/stable")
RESOURCES = Path(__file__).resolve().parent.parent / "resources"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:160.0) "
    "Gecko/20100101 Firefox/160.0"
)


@dataclass(frozen=True)
class Failure:
    pid: str
    result: str
    final_url: str
    detail: str = ""


def load_stable_pids(
    resources: Path,
) -> tuple[dict[str, tuple[str, ...]], list[Failure]]:
    """Read both historical pid:PID and current pid:Pid registrations."""
    paths = sorted(resources.rglob("*.ttl"))
    if not paths:
        raise ValueError(f"No Turtle files found under {resources}")
    graph = Graph()
    failures = []
    for path in paths:
        try:
            parsed = Graph().parse(path, format="turtle")
        except (OSError, SyntaxError, ValueError, ParserError) as error:
            failures.append(Failure(str(path), "Invalid Turtle", "", str(error)))
            continue
        graph += parsed
    subjects = set(graph.subjects(RDF.type, PID.PID)) | set(
        graph.subjects(RDF.type, PID.Pid)
    )
    registrations = {
        str(subject): tuple(
            sorted({str(url) for url in graph.objects(subject, SCHEMA.url)})
        )
        for subject in sorted(subjects, key=str)
        if (subject, SCHEMA.status, STABLE) in graph
    }
    return registrations, failures


def check_resolution(client: httpx.Client, url: str) -> Failure | None:
    """Follow GET redirects, retrying HTTP 403 once with a browser User-Agent."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return Failure(
                url, "Invalid URL", url, "schema:url must be an absolute HTTP(S) URL"
            )
        for attempt in range(2):
            headers = {"User-Agent": BROWSER_USER_AGENT} if attempt else {}
            with client.stream(
                "GET", url, headers=headers, follow_redirects=True
            ) as response:
                if response.status_code == httpx.codes.OK:
                    return None
                if response.status_code == httpx.codes.FORBIDDEN and not attempt:
                    continue
                return Failure(
                    url,
                    f"HTTP {response.status_code}",
                    str(response.url),
                    response.reason_phrase
                    + (" (after User-Agent retry)" if attempt else ""),
                )
    except httpx.RequestError as error:
        return Failure(url, type(error).__name__, str(error.request.url), str(error))
    except (httpx.InvalidURL, ValueError) as error:
        return Failure(url, "Invalid URL", url, str(error))
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path, default=RESOURCES)
    parser.add_argument(
        "--timeout",
        type=float,
        default=20,
        help="Network timeout in seconds (default: 20)",
    )
    parser.add_argument(
        "--max-redirects",
        type=int,
        default=20,
        help="Maximum redirects per PID (default: 20)",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.max_redirects < 0:
        parser.error(
            "--timeout must be positive and --max-redirects must be non-negative"
        )
    try:
        registrations, failures = load_stable_pids(args.resources)
    except ValueError as error:
        parser.error(str(error))
    if not registrations and not failures:
        parser.error(f"No stable PID registrations found under {args.resources}")

    failures.extend(
        [
            Failure(
                subject,
                "Missing schema:url",
                "",
                "Cannot determine the PID URL to request",
            )
            for subject, urls in registrations.items()
            if not urls
        ]
    )
    urls = sorted({url for values in registrations.values() for url in values})
    console = Console(markup=False, highlight=False)
    with httpx.Client(timeout=args.timeout, max_redirects=args.max_redirects) as client:
        # HTTPX supplies Accept: */* by default. Remove it entirely, including on redirects.
        client.headers.pop("Accept", None)
        with console.status(f"Checking {len(urls)} stable PID URLs…") as progress:
            for index, url in enumerate(urls, 1):
                progress.update(f"Checking stable PID {index}/{len(urls)}: {url}")
                failure = check_resolution(client, url)
                if failure:
                    failures.append(failure)

    table = Table(title="Stable PID resolution failures and unreadable source files")
    for heading in ("PID / Source file", "Result", "Final URL", "Detail"):
        table.add_column(heading, overflow="fold")
    for failure in failures:
        table.add_row(failure.pid, failure.result, failure.final_url, failure.detail)
    console.print(table)
    console.print(
        f"Checked {len(urls)} unique URLs from {len(registrations)} stable registrations: "
        f"{len(failures)} failure(s)."
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
