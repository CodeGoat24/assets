import json
import os
import random
import sys
import time
from datetime import datetime

from scholarly import scholarly, ProxyGenerator

SCHOLAR_ID = os.environ["GOOGLE_SCHOLAR_ID"]
MAX_TRIES = int(os.environ.get("GS_MAX_TRIES", "5"))
RESULTS_DIR = "results"


def setup_proxy() -> None:
    """Route requests through ScraperAPI when a key is provided.

    GitHub Actions runners are frequently blocked by Google Scholar. Set the
    SCRAPERAPI_KEY repository secret (free tier is enough for a daily crawl)
    to make the crawler reliable. Without a key we fall back to direct access.
    """
    key = os.environ.get("SCRAPERAPI_KEY")
    if not key:
        print("No SCRAPERAPI_KEY set, using direct connection.", file=sys.stderr)
        return
    pg = ProxyGenerator()
    if pg.ScraperAPI(key):
        scholarly.use_proxy(pg)
        print("Using ScraperAPI proxy.", file=sys.stderr)
    else:
        print("ScraperAPI proxy setup failed, using direct connection.", file=sys.stderr)


def fetch_author() -> dict:
    author = scholarly.search_author_id(SCHOLAR_ID)
    scholarly.fill(author, sections=["basics", "indices", "counts", "publications"])
    return author


def main() -> None:
    setup_proxy()

    author = None
    for attempt in range(1, MAX_TRIES + 1):
        try:
            author = fetch_author()
            break
        except Exception as exc:  # noqa: BLE001
            print(
                f"[attempt {attempt}/{MAX_TRIES}] {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            if attempt < MAX_TRIES:
                delay = random.uniform(30, 90)
                print(f"Retrying in {delay:.0f}s...", file=sys.stderr)
                time.sleep(delay)

    if author is None:
        print("All attempts failed; previous data on the stats branch is kept.", file=sys.stderr)
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

    print(f"Done. citedby={author['citedby']}, publications={len(author['publications'])}", file=sys.stderr)


if __name__ == "__main__":
    main()
