"""
APAC Offshore Wind News Monitor
================================
Fetches news across Taiwan, Japan, Korea, China, Vietnam, Philippines and
Australia (plus pan-APAC trade press), filters for offshore-wind relevance,
uses Claude to classify/translate/summarize, and emails a weekly digest.

USAGE
-----
    pip install feedparser requests
    export ANTHROPIC_API_KEY=sk-ant-...
    python monitor.py                     # writes digest_YYYY-MM-DD.md and emails it

In production this runs automatically via the included GitHub Actions
workflow (.github/workflows/weekly-digest.yml) — see README.md for setup.

DESIGN NOTES
------------
- Collection is RSS-based: direct trade-press feeds + Google News RSS
  queries per market/language. No scraping of sites that block it.
- Filtering happens in two passes: a cheap keyword pass first, then an LLM
  relevance/classification pass on survivors only (keeps API cost low).
- Translation and summarization happen in ONE Claude call per article,
  which preserves industry-specific meaning (GW figures, vessel specs,
  auction terms) better than a separate generic MT step.
- Original-language headline + source URL are always preserved in the
  digest for traceability, even though summaries are in English.
- Default email settings below are configured for Microsoft 365 / Outlook
  (smtp.office365.com, port 587, STARTTLS). Override via GitHub Secrets if
  you use a different provider — see README.md.
"""

import os
import re
import json
import time
import hashlib
import datetime as dt
from urllib.parse import quote

import feedparser
import requests

from config import (
    MARKETS, GLOBAL_TRADE_FEEDS, CORE_KEYWORDS, WATCH_ENTITIES,
    VESSEL_CONTRACT_KEYWORDS, LOOKBACK_DAYS, MAX_ARTICLES_PER_MARKET,
    MIN_RELEVANCE_FOR_DIGEST, MAX_ITEMS_PER_MARKET, MIN_ITEMS_PER_MARKET,
    MAX_TOP_LINE_ITEMS, TRUSTED_DOMAINS, MARKET_FLAGS,
)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = "claude-sonnet-4-6"  # swap for whichever current model you have access to

# Email delivery settings — all read from environment variables / GitHub
# Secrets, nothing sensitive is hardcoded here. Defaults are set for
# Microsoft 365 / Outlook; override via secrets for Gmail or another provider.
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")          # your company email address
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")  # app password (see README)
DIGEST_RECIPIENTS = os.environ.get("DIGEST_RECIPIENTS", "")  # comma-separated emails


# ---------------------------------------------------------------------------
# 1. COLLECTION
# ---------------------------------------------------------------------------

def google_news_rss_url(query: str, lang: str, country: str) -> str:
    q = quote(query)
    ceid = f"{country}:{lang.split('-')[0]}"
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={country}&ceid={ceid}"


def fetch_feed(url: str, timeout: int = 15):
    """Fetch and parse a single RSS/Atom feed. Returns [] on any failure so
    one dead feed doesn't take down the whole run."""
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        parsed = feedparser.parse(resp.content)
        return parsed.entries
    except Exception as e:
        print(f"  [warn] could not fetch {url}: {e}")
        return []


def collect_market_articles(market: str, cfg: dict) -> list:
    articles = []
    for feed_url in cfg.get("feeds", []):
        for entry in fetch_feed(feed_url):
            articles.append(normalize_entry(entry, market, source_type="direct_feed"))

    for query, lang, country in cfg.get("gnews_queries", []):
        url = google_news_rss_url(query, lang, country)
        for entry in fetch_feed(url):
            articles.append(normalize_entry(entry, market, source_type="gnews", query=query))

    return dedupe(articles)


def collect_global_articles() -> list:
    articles = []
    for feed_url in GLOBAL_TRADE_FEEDS:
        for entry in fetch_feed(feed_url):
            articles.append(normalize_entry(entry, market="Global/APAC", source_type="direct_feed"))
    return dedupe(articles)


def normalize_entry(entry, market: str, source_type: str, query: str = None) -> dict:
    title = getattr(entry, "title", "").strip()
    link = getattr(entry, "link", "")
    summary = getattr(entry, "summary", "") or getattr(entry, "description", "")
    published = getattr(entry, "published", "") or getattr(entry, "updated", "")
    source = getattr(entry, "source", {}).get("title") if hasattr(entry, "source") else None

    # feedparser gives a parsed time.struct_time (UTC) when it can determine
    # one; we convert to a real datetime so we can filter by LOOKBACK_DAYS.
    published_dt = None
    struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if struct:
        try:
            published_dt = dt.datetime(*struct[:6], tzinfo=dt.timezone.utc)
        except Exception:
            published_dt = None

    return {
        "id": hashlib.md5((title + link).encode("utf-8")).hexdigest()[:10],
        "market": market,
        "title": title,
        "link": link,
        "summary_raw": re.sub("<[^<]+?>", "", summary)[:600],
        "published": published,
        "published_dt": published_dt,
        "source": source or _domain_from_url(link),
        "source_type": source_type,
        "gnews_query": query,
    }


def within_lookback_window(article: dict) -> bool:
    """Keep the article if it's within LOOKBACK_DAYS, OR if the feed didn't
    provide a parseable date at all (some sources omit it) — we don't want
    to silently drop everything just because a date field is missing, but
    anything with a clear date outside the window is excluded."""
    published_dt = article.get("published_dt")
    if published_dt is None:
        return True
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=LOOKBACK_DAYS)
    return published_dt >= cutoff


def _domain_from_url(url: str) -> str:
    m = re.search(r"https?://([^/]+)/", url + "/")
    return m.group(1) if m else url


def dedupe(articles: list) -> list:
    seen, out = set(), []
    for a in articles:
        key = a["title"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(a)
    return out


# ---------------------------------------------------------------------------
# 2. CHEAP KEYWORD PRE-FILTER
# ---------------------------------------------------------------------------

def keyword_prefilter(articles: list, native_keywords: list) -> list:
    all_terms = [k.lower() for k in CORE_KEYWORDS + WATCH_ENTITIES] + native_keywords
    kept = []
    for a in articles:
        if not within_lookback_window(a):
            continue
        haystack = f"{a['title']} {a['summary_raw']}".lower()
        if any(term.lower() in haystack for term in all_terms):
            kept.append(a)
    return kept[:MAX_ARTICLES_PER_MARKET]


# ---------------------------------------------------------------------------
# 3. LLM CLASSIFICATION + TRANSLATION + SUMMARIZATION
# ---------------------------------------------------------------------------

CLASSIFY_PROMPT = """You are a research analyst monitoring offshore wind news in Asia-Pacific \
for Cadeler, an offshore wind turbine installation vessel (WTIV) operator. \
Given the article title and snippet below (which may be in a non-English language), do the following:

1. Translate the title into clear English if it isn't already.
2. Write a 1-2 sentence English summary of what the article is about, based only on the \
   information given (do not invent details not present in the text).
3. Classify relevance to Cadeler's business on a 0-3 scale:
   0 = not relevant to offshore wind
   1 = general offshore wind market/policy news
   2 = relevant to offshore wind supply chain, developers, or financing
   3 = directly relevant to installation vessels, T&I contracts, or Cadeler/its competitors
4. Assign a theme tag: one of [Vessel & Contract, Policy & Auctions, Project Delay/Distress, \
   Financing & PPA, Supply Chain, Corporate/M&A, Other]
5. Flag "low_confidence": true if the snippet is too short/ambiguous to summarize reliably.

Respond ONLY with a JSON object, no other text:
{{"english_title": "...", "summary": "...", "relevance": 0-3, "theme": "...", "low_confidence": true/false}}

ARTICLE TITLE: {title}
ARTICLE SNIPPET: {snippet}
"""


def classify_article(article: dict) -> dict:
    if not ANTHROPIC_API_KEY:
        article.update({
            "english_title": article["title"],
            "summary": article["summary_raw"][:200],
            "relevance": 1,
            "theme": "Other",
            "low_confidence": True,
        })
        return article

    prompt = CLASSIFY_PROMPT.format(title=article["title"], snippet=article["summary_raw"])
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["content"][0]["text"]
        text = re.sub(r"^```json|```$", "", text.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(text)
        article.update(parsed)
    except Exception as e:
        print(f"  [warn] classification failed for '{article['title'][:60]}': {e}")
        article.update({
            "english_title": article["title"],
            "summary": article["summary_raw"][:200],
            "relevance": 1,
            "theme": "Other",
            "low_confidence": True,
        })
    return article


def is_vessel_contract_item(article: dict) -> bool:
    haystack = f"{article.get('english_title','')} {article.get('summary','')}".lower()
    return any(k.lower() in haystack for k in VESSEL_CONTRACT_KEYWORDS)


def is_trusted_source(article: dict) -> bool:
    domain = (article.get("source") or "").lower()
    link = (article.get("link") or "").lower()
    return any(td in domain or td in link for td in TRUSTED_DOMAINS)


def curate(articles: list, limit: int, allow_fallback: bool = False, min_items: int = 0) -> list:
    """Apply the relevance bar, drop low-confidence noise, sort by
    relevance then source credibility, and cap to `limit` items — this is
    what keeps the digest short and high-signal instead of exhaustive.

    If allow_fallback=True, guarantees at least `min_items` results as long
    as `articles` is non-empty — topped up with the next-best-scoring items
    even if they're below MIN_RELEVANCE_FOR_DIGEST — so a market with real
    news that week never renders as empty just because everything happened
    to score as "general market news" rather than "high priority". A market
    with zero collected articles still renders as empty, as it should.
    """
    kept = [
        a for a in articles
        if a.get("relevance", 0) >= MIN_RELEVANCE_FOR_DIGEST
        and not (a.get("low_confidence") and a.get("relevance", 0) < 3)
    ]
    kept.sort(key=lambda a: (a.get("relevance", 0), is_trusted_source(a)), reverse=True)

    if allow_fallback and len(kept) < min_items and articles:
        kept_ids = {a["id"] for a in kept}
        remaining = [a for a in articles if a["id"] not in kept_ids]
        remaining.sort(key=lambda a: (a.get("relevance", 0), is_trusted_source(a)), reverse=True)
        needed = min_items - len(kept)
        for a in remaining[:needed]:
            a["_below_bar"] = True
        kept = kept + remaining[:needed]
        kept.sort(key=lambda a: (a.get("relevance", 0), is_trusted_source(a)), reverse=True)

    return kept[:max(limit, min_items)]


# ---------------------------------------------------------------------------
# 4. DIGEST ASSEMBLY
# ---------------------------------------------------------------------------

def build_digest(market_results: dict, global_results: list) -> str:
    """Markdown version — used for the saved file and as the plain-text
    email fallback. Curated to high-signal items only."""
    today = dt.date.today().isoformat()
    lines = [f"# APAC Offshore Wind Weekly Digest — {today}", ""]

    all_items = [a for items in market_results.values() for a in items] + global_results
    top_items = curate(all_items, MAX_TOP_LINE_ITEMS)

    lines.append("## Top-line summary")
    if not top_items:
        lines.append("_No items met the relevance bar this week._")
    for a in top_items:
        flag = MARKET_FLAGS.get(a["market"], "")
        anchor = " ⚓" if is_vessel_contract_item(a) else ""
        lines.append(f"- {flag} **[{a['market']}]** {a['english_title']}{anchor} — {a['summary']} ([source]({a['link']}))")
    lines.append("")

    vessel_items = curate([a for a in all_items if is_vessel_contract_item(a)], MAX_TOP_LINE_ITEMS)
    lines.append("## ⚓ Vessel & contract watch")
    if not vessel_items:
        lines.append("_No vessel/contract items this week._")
    for a in vessel_items:
        flag = MARKET_FLAGS.get(a["market"], "")
        lines.append(f"- {flag} **[{a['market']}]** {a['english_title']} — {a['summary']} ([source]({a['link']}))")
    lines.append("")

    lines.append("## Market-by-market roundup")
    for market, items in market_results.items():
        curated = curate(items, MAX_ITEMS_PER_MARKET, allow_fallback=True, min_items=MIN_ITEMS_PER_MARKET)
        if not curated:
            continue
        flag = MARKET_FLAGS.get(market, "")
        lines.append(f"### {flag} {market}")
        for a in curated:
            tag = f"`{a.get('theme','Other')}`"
            note = " _(below usual bar — shown so this market isn't empty)_" if a.get("_below_bar") else ""
            lines.append(f"- {tag} {a['english_title']}{note} — {a['summary']} ([source]({a['link']}))")
        lines.append("")

    curated_global = curate(global_results, MAX_ITEMS_PER_MARKET)
    if curated_global:
        lines.append("### 🌏 Global / pan-APAC trade press")
        for a in curated_global:
            lines.append(f"- {a['english_title']} — {a['summary']} ([source]({a['link']}))")
        lines.append("")

    return "\n".join(lines)


def build_digest_html(market_results: dict, global_results: list) -> str:
    """News-style HTML version for the email body. Built with tables and
    inline styles only (no flexbox/grid, no external CSS) because Outlook
    desktop renders email HTML with Word's engine, which ignores most modern
    CSS — tables are the one layout method that reliably works there."""
    today = dt.date.today().strftime("%B %d, %Y")
    all_items = [a for items in market_results.values() for a in items] + global_results
    top_items = curate(all_items, MAX_TOP_LINE_ITEMS)
    vessel_items = curate([a for a in all_items if is_vessel_contract_item(a)], MAX_TOP_LINE_ITEMS)

    NAVY = "#1a2b4a"
    GOLD = "#c9a15a"
    TEXT = "#2b2b2b"
    MUTED = "#6b6b6b"
    BORDER = "#e2e2e2"
    BG = "#f7f7f5"

    def item_row(a, show_market=True):
        flag = MARKET_FLAGS.get(a["market"], "") if show_market else ""
        market_tag = f'{flag} <span style="color:{GOLD};font-weight:bold;">{a["market"]}</span> · ' if show_market else ""
        anchor = ' <span style="color:#a35c1d;">⚓</span>' if is_vessel_contract_item(a) else ""
        below_bar_note = f'<div style="font-size:11px;color:{MUTED};font-style:italic;margin-top:2px;">Below usual relevance bar — shown so this market isn\'t left empty</div>' if a.get("_below_bar") else ""
        return f"""
        <tr><td style="padding:14px 0;border-bottom:1px solid {BORDER};">
          <div style="font-size:12px;color:{MUTED};margin-bottom:4px;">{market_tag}{a.get('theme','')}</div>
          <div style="font-size:16px;font-weight:bold;color:{TEXT};margin-bottom:4px;">{a['english_title']}{anchor}</div>
          <div style="font-size:14px;color:{TEXT};line-height:1.5;margin-bottom:4px;">{a['summary']}</div>
          <a href="{a['link']}" style="font-size:12px;color:{NAVY};text-decoration:underline;">Read more →</a>
          {below_bar_note}
        </td></tr>"""

    def section_header(title):
        return f"""
        <tr><td style="padding:22px 0 8px 0;border-bottom:2px solid {NAVY};">
          <span style="font-size:15px;font-weight:bold;color:{NAVY};letter-spacing:0.5px;">{title}</span>
        </td></tr>"""

    body_rows = []

    body_rows.append(section_header("Top Stories"))
    if top_items:
        for a in top_items:
            body_rows.append(item_row(a))
    else:
        body_rows.append(f'<tr><td style="padding:14px 0;color:{MUTED};font-size:13px;">No items met the relevance bar this week.</td></tr>')

    if vessel_items:
        body_rows.append(section_header("⚓ Vessel &amp; Contract Watch"))
        for a in vessel_items:
            body_rows.append(item_row(a))

    for market, items in market_results.items():
        curated = curate(items, MAX_ITEMS_PER_MARKET, allow_fallback=True, min_items=MIN_ITEMS_PER_MARKET)
        if not curated:
            continue
        flag = MARKET_FLAGS.get(market, "")
        body_rows.append(section_header(f"{flag} {market}"))
        for a in curated:
            body_rows.append(item_row(a, show_market=False))

    curated_global = curate(global_results, MAX_ITEMS_PER_MARKET)
    if curated_global:
        body_rows.append(section_header("🌏 Global / Pan-APAC Trade Press"))
        for a in curated_global:
            body_rows.append(item_row(a, show_market=False))

    rows_html = "\n".join(body_rows)

    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG};padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="640" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid {BORDER};">
<tr><td style="background:{NAVY};padding:24px 28px;">
  <div style="font-size:20px;font-weight:bold;color:#ffffff;">APAC Offshore Wind Weekly</div>
  <div style="font-size:13px;color:{GOLD};margin-top:4px;">{today} · covering the past {LOOKBACK_DAYS} days</div>
</td></tr>
<tr><td style="padding:8px 28px 28px 28px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    {rows_html}
  </table>
</td></tr>
<tr><td style="padding:16px 28px;background:{BG};border-top:1px solid {BORDER};">
  <div style="font-size:11px;color:{MUTED};">Auto-generated · sourced from industry trade press and national news outlets · summaries are AI-generated — verify original sources before making decisions.</div>
</td></tr>
</table>
</td></tr>
</table>
"""


# ---------------------------------------------------------------------------
# 4b. EMAIL DELIVERY
# ---------------------------------------------------------------------------

def send_email(digest_markdown: str, digest_html: str):
    """Emails the digest as both plain text (markdown) and rich HTML
    (news-style layout). Silently skips if SMTP settings / recipients
    aren't configured, so local testing without email setup still works."""
    if not (SMTP_USER and SMTP_PASSWORD and DIGEST_RECIPIENTS):
        print("  [info] Email not configured (SMTP_USER/SMTP_PASSWORD/DIGEST_RECIPIENTS "
              "missing) — skipping send. Digest was still saved to file.")
        return

    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    recipients = [r.strip() for r in DIGEST_RECIPIENTS.split(",") if r.strip()]
    subject = f"APAC Offshore Wind Weekly Digest — {dt.date.today().isoformat()}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(digest_markdown, "plain", "utf-8"))
    msg.attach(MIMEText(digest_html, "html", "utf-8"))

    try:
        # Port 465 = implicit SSL (Gmail's default).
        # Port 587 = STARTTLS (Microsoft 365 / Outlook's default — this is
        # our default above, and most corporate mail servers use this too).
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, recipients, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"  Emailed digest to: {', '.join(recipients)}")
    except Exception as e:
        print(f"  [warn] email send failed: {e}")


# ---------------------------------------------------------------------------
# 5. MAIN
# ---------------------------------------------------------------------------

def run():
    market_results = {}

    for market, cfg in MARKETS.items():
        print(f"Collecting: {market}")
        raw = collect_market_articles(market, cfg)
        filtered = keyword_prefilter(raw, cfg.get("native_keywords", []))
        print(f"  {len(raw)} raw -> {len(filtered)} after keyword+date filter")
        classified = [classify_article(a) for a in filtered]
        scores = [a.get("relevance", 0) for a in classified]
        print(f"  relevance scores this week: {scores}")
        market_results[market] = classified
        time.sleep(0.5)

    print("Collecting: Global/APAC trade press")
    global_raw = collect_global_articles()
    global_filtered = keyword_prefilter(global_raw, [])
    global_classified = [classify_article(a) for a in global_filtered]
    global_classified = [a for a in global_classified if a.get("relevance", 0) >= 1]

    digest = build_digest(market_results, global_classified)
    digest_html = build_digest_html(market_results, global_classified)

    out_path = f"digest_{dt.date.today().isoformat()}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(digest)
    print(f"\nDigest written to {out_path}")

    send_email(digest, digest_html)

    return out_path


if __name__ == "__main__":
    run()
