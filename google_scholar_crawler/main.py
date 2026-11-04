"""Crawl a Google Scholar author profile and dump it as JSON.

Two fetch strategies:

1. ScraperAPI (recommended for GitHub Actions). Google Scholar blocks data-center
   IPs, so when SCRAPERAPI_KEY is set every page is fetched through ScraperAPI's
   HTTP API with `premium=true&render=true`, which is the only combination we
   found that reliably returns the real profile page. Failed ScraperAPI calls
   (HTTP 500, Google's 404 bot page) are not billed, so we retry them freely.

2. Direct connection (works from residential IPs such as a laptop).
"""

import json
import os
import random
import sys
import time
from datetime import datetime

import requests
from scholarly import scholarly
from scholarly.author_parser import AuthorParser

SCHOLAR_ID = os.environ["GOOGLE_SCHOLAR_ID"]
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "").strip()
MAX_TRIES = int(os.environ.get("GS_MAX_TRIES", "3"))
PAGE_TRIES = int(os.environ.get("GS_PAGE_TRIES", "6"))
RESULTS_DIR = "results"

SCRAPERAPI_ENDPOINT = "https://api.scraperapi.com/"
SCRAPERAPI_TIMEOUT = 170  # ScraperAPI gives up after ~70s per attempt; render can be slow.


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def looks_like_profile(html: str) -> bool:
    return "gsc_prf_in" in html and "gsc_a_tr" in html


def scraperapi_get_page(url: str, premium: bool = False) -> str:  # noqa: ARG001
    """Drop-in replacement for scholarly's Navigator._get_page."""
    last_error = "unknown"
    for attempt in range(1, PAGE_TRIES + 1):
        try:
            resp = requests.get(
                SCRAPERAPI_ENDPOINT,
                params={
                    "api_key": SCRAPERAPI_KEY,
                    "url": url,
                    "premium": "true",
                    "render": "true",
                },
                timeout=SCRAPERAPI_TIMEOUT,
            )
            if resp.status_code == 200 and looks_like_profile(resp.text):
                log(f"ScraperAPI page fetched on attempt {attempt}: {url}")
                return resp.text.replace("\xa0", " ")
            last_error = f"http={resp.status_code} size={len(resp.text)}"
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        log(f"ScraperAPI attempt {attempt}/{PAGE_TRIES} failed ({last_error})")
        if attempt < PAGE_TRIES:
            time.sleep(random.uniform(5, 15))
    raise RuntimeError(f"ScraperAPI could not fetch {url}: {last_error}")


def configure_fetcher() -> None:
    if SCRAPERAPI_KEY:
        navigator = scholarly._Scholarly__nav  # noqa: SLF001
        navigator._get_page = scraperapi_get_page  # noqa: SLF001
        log("Using ScraperAPI (premium + render) for all requests.")
    else:
        log("No SCRAPERAPI_KEY set, using direct connection.")


def fetch_author() -> dict:
    # scholarly.search_author_id() would fetch the profile page once for
    # 'basics' and fill() would fetch it again. Build the container directly so
    # a run needs exactly one successful page fetch (matters for ScraperAPI credits).
    navigator = scholarly._Scholarly__nav  # noqa: SLF001
    author = AuthorParser(navigator).get_author(SCHOLAR_ID)
    scholarly.fill(author, sections=["basics", "indices", "counts", "publications"])
    return author


def main() -> None:
    configure_fetcher()

    author = None
    for attempt in range(1, MAX_TRIES + 1):
        try:
            author = fetch_author()
            break
        except Exception as exc:  # noqa: BLE001
            log(f"[attempt {attempt}/{MAX_TRIES}] {type(exc).__name__}: {exc}")
            if attempt < MAX_TRIES:
                delay = random.uniform(20, 60)
                log(f"Retrying in {delay:.0f}s...")
                time.sleep(delay)

    if author is None:
        log("All attempts failed; previous data on the stats branch is kept.")
        sys.exit(1)

    author["updated"] = str(datetime.now())
    author["publications"] = {v["author_pub_id"]: v for v in author["publications"]}
    print(json.dumps(author, indent=2, ensure_ascii=False))

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(os.path.join(RESULTS_DIR, "gs_data.json"), "w", encoding="utf-8") as outfile:
        json.dump(author, outfile, ensure_ascii=False)

    shieldio_data = {
        "schemaVersion": 1,
        "label": "citations",
        "message": str(author["citedby"]),
    }
    with open(os.path.join(RESULTS_DIR, "gs_data_shieldsio.json"), "w", encoding="utf-8") as outfile:
        json.dump(shieldio_data, outfile, ensure_ascii=False)

    log(f"Done. citedby={author['citedby']}, publications={len(author['publications'])}")


if __name__ == "__main__":
    main()
