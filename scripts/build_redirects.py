"""Build one Apache redirect configuration into .conf files per PID sponsor."""

from __future__ import annotations

import argparse
import os
import shutil
from collections import defaultdict
from pathlib import Path

from redirect_source import load_redirects, sponsor_slug


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-type", choices=("local", "sparql"), default="local")
    parser.add_argument("--source", default="resources/pids")
    parser.add_argument("--username", default=os.getenv("SPARQL_USERNAME"))
    parser.add_argument("--password", default=os.getenv("SPARQL_PASSWORD"))
    parser.add_argument("--output", type=Path, default=Path("tests/conf"))
    args = parser.parse_args()

    redirects = load_redirects(args.source_type, args.source, args.username, args.password)
    grouped = defaultdict(list)
    for redirect in redirects:
        grouped[sponsor_slug(redirect.sponsor)].append(redirect)

    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    for sponsor, entries in sorted(grouped.items()):
        content = []
        for entry in entries:
            content.extend((f"# {entry.pid}", entry.rules.strip(), ""))
        (args.output / f"{sponsor}.conf").write_text("\n".join(content).rstrip() + "\n")
    print(f"Built {len(redirects)} redirects in {len(grouped)} sponsor configuration files under {args.output}")


if __name__ == "__main__":
    main()
