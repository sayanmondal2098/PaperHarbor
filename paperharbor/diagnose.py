"""Inspect discovery for one DOI/URL without downloading or modifying a library."""

import argparse
import json
from dataclasses import asdict

from paperharbor.providers.aggregator import ProviderAggregator
from paperharbor.providers.matching import conflicts_with_doi
from paperharbor.single_paper import SinglePaperReader


def diagnose(identifier, title="", email=None, expanded=False):
    reference = SinglePaperReader(identifier, title=title, email=email).get_references()[0]
    aggregator = ProviderAggregator(email=email)
    candidates, publisher_url = aggregator.find_candidates(reference)
    if expanded:
        candidates += aggregator.find_fallback_candidates(reference)
    unique = {}
    rejected = []
    for candidate in candidates:
        if conflicts_with_doi(reference, candidate.url) or conflicts_with_doi(reference, candidate.landing_page):
            rejected.append(candidate.url)
        else:
            unique.setdefault(candidate.url, asdict(candidate))
    return {
        "reference": asdict(reference), "publisher_url": publisher_url,
        "candidates": list(unique.values()), "provider_errors": aggregator.errors,
        "rejected_doi_conflicts": rejected,
        "note": "Discovery only. Candidate URLs have not been downloaded or verified as PDFs.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Inspect one paper's download candidates without downloading.")
    parser.add_argument("identifier", help="DOI or HTTP(S) article URL")
    parser.add_argument("--title", default="", help="Title if bibliographic metadata is unavailable")
    parser.add_argument("--email", help="Contact email for provider requests")
    parser.add_argument("--expanded", action="store_true", help="Query fallback providers as well")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(diagnose(args.identifier, args.title, args.email, args.expanded),
                         ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Could not inspect paper: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
