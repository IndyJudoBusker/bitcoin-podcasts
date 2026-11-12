#!/usr/bin/env python3
"""
Apple-Podcasts durchsuchen und die jeweils neueste Folge zu einem RSS-Feed aggregieren.
"""

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import feedparser
import requests
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
MEDIA_NS = "http://search.yahoo.com/mrss/"

ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("atom", ATOM_NS)
ET.register_namespace("media", MEDIA_NS)

# Workaround, damit ElementTree echte CDATA-Sektionen schreibt
_original_escape_cdata = ET._escape_cdata


def _escape_cdata(text):
    if isinstance(text, str) and text.startswith("<![CDATA[") and text.endswith("]]>"):
        return text
    return _original_escape_cdata(text)


ET._escape_cdata = _escape_cdata


def cdata(text: str) -> str:
    return f"<![CDATA[{text}]]>"


# ---------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------
def get_href(obj) -> str | None:
    """Extrahiere eine URL aus feedparser-Dict/string-Attributen."""
    if not obj:
        return None
    if isinstance(obj, dict):
        return obj.get("href")
    if isinstance(obj, str):
        return obj
    return getattr(obj, "href", None)


def search_podcasts(term: str, country: str = "de", limit: int = 100) -> list[str]:
    """iTunes/Apple Podcasts API durchsuchen."""
    params = {
        "term": term,
        "entity": "podcast",
        "country": country,
        "limit": limit,
    }
    headers = {
        "User-Agent": "PodcastAggregator/1.0",
        "Accept": "application/json",
    }
    response = requests.get(
        "https://itunes.apple.com/search",
        params=params,
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    return [r["feedUrl"] for r in data.get("results", []) if r.get("feedUrl")]


def fetch_feed(feed_url: str) -> feedparser.FeedParserDict | None:
    """RSS-Feed mit requests laden und mit feedparser parsen."""
    headers = {
        "User-Agent": "PodcastAggregator/1.0",
        "Accept": "application/rss+xml, application/xml, application/atom+xml, */*",
    }
    try:
        response = requests.get(feed_url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as exc:
        logging.warning("Konnte Feed nicht laden %s: %s", feed_url, exc)
        return None

    feed = feedparser.parse(response.content)
    if feed.get("bozo"):
        logging.info(
            "Feed-Parser-Warnung bei %s: %s",
            feed_url,
            feed.get("bozo_exception"),
        )
    return feed


def parse_entry_date(entry) -> datetime:
    """Erzeuge ein aware datetime aus published/updated_parsed."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def get_latest_episode(feed_url: str) -> dict | None:
    logging.info("Lade Feed: %s", feed_url)

    feed = fetch_feed(feed_url)
    if feed is None:
        return None

    podcast_title = feed.feed.get("title", feed_url)
    logging.info("  🎙 Podcast: %s", podcast_title)

    if not feed.entries:
        logging.warning("  ⚠️ Keine Episoden gefunden")
        return None

    # Neueste Episode anhand Veröffentlichungsdatum ermitteln
    latest_entry = max(feed.entries, key=parse_entry_date)

    # Enclosure (Audio-Datei)
    enclosure_url: str | None = None
    enclosure_length = "0"
    enclosure_type = "audio/mpeg"

    if latest_entry.get("enclosures"):
        enc = latest_entry.enclosures[0]
        enclosure_url = enc.get("href")
        enclosure_length = enc.get("length") or "0"
        enclosure_type = enc.get("type") or "audio/mpeg"

    if not enclosure_url:
        logging.warning("  ⚠️ Keine Audio-Datei (enclosure) gefunden")
        return None

    # Bild: Episode → Podcast
    episode_image = (
        get_href(latest_entry.get("image"))
        or get_href(latest_entry.get("itunes_image"))
        or get_href(feed.feed.get("image"))
        or get_href(feed.feed.get("itunes_image"))
    )

    # Beschreibung mit Fallback-Kette
    episode_description = ""
    if latest_entry.get("content"):
        episode_description = latest_entry.content[0].value
    elif latest_entry.get("itunes_summary"):
        episode_description = latest_entry.itunes_summary
    elif latest_entry.get("description"):
        episode_description = latest_entry.description
    elif latest_entry.get("summary"):
        episode_description = latest_entry.summary

    duration = latest_entry.get("itunes_duration")

    logging.info("  ✔ Neueste Folge: %s", latest_entry.get("title", "Unbekannte Folge"))

    return {
        "podcast_title": podcast_title,
        "episode_title": latest_entry.get("title", "Unbekannte Folge"),
        "link": latest_entry.get("link", ""),
        "published": latest_entry.get("published_parsed"),
        "published_dt": parse_entry_date(latest_entry),
        "audio_url": enclosure_url,
        "audio_length": str(enclosure_length),
        "audio_type": enclosure_type,
        "guid": latest_entry.get("id", latest_entry.get("link", "")),
        "episode_image": episode_image,
        "episode_description": episode_description,
        "duration": duration,
    }


def generate_rss(
    episodes: list[dict],
    output_file: Path,
    self_link: str,
    feed_image: str,
) -> None:
    episodes = sorted(
        episodes,
        key=lambda ep: ep.get("published_dt") or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = "Bitcoin – Aktuelle Podcast-Folgen"
    ET.SubElement(channel, "link").text = self_link
    ET.SubElement(channel, "description").text = (
        "Die jeweils neueste Folge aller Apple-Podcasts zum Thema Bitcoin"
    )
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc)
    )

    ET.SubElement(
        channel, f"{{{ATOM_NS}}}link", rel="self", href=self_link, type="application/rss+xml"
    )
    ET.SubElement(channel, f"{{{ITUNES_NS}}}image", href=feed_image)

    for ep in episodes:
        item = ET.SubElement(channel, "item")

        ET.SubElement(item, "title").text = (
            f"{ep['podcast_title']} – {ep['episode_title']}"
        )
        ET.SubElement(item, "link").text = ep["link"]
        ET.SubElement(item, "guid").text = ep["guid"]

        if ep.get("published"):
            pub_date = datetime(*ep["published"][:6], tzinfo=timezone.utc)
            ET.SubElement(item, "pubDate").text = format_datetime(pub_date)

        if ep.get("episode_image"):
            ET.SubElement(
                item, f"{{{ITUNES_NS}}}image", href=ep["episode_image"]
            )
            ET.SubElement(
                item, f"{{{MEDIA_NS}}}thumbnail", url=ep["episode_image"]
            )
            ET.SubElement(
                item,
                f"{{{MEDIA_NS}}}content",
                url=ep["episode_image"],
                medium="image",
                type="image/jpeg",
            )

        if ep.get("audio_url"):
            ET.SubElement(
                item,
                "enclosure",
                url=ep["audio_url"],
                length=str(ep["audio_length"]),
                type=ep["audio_type"],
            )

        if ep.get("duration"):
            ET.SubElement(item, f"{{{ITUNES_NS}}}duration").text = ep["duration"]

        description = ep.get("episode_description", "").strip()
        if description:
            ET.SubElement(item, "description").text = cdata(description)
            ET.SubElement(item, f"{{{ITUNES_NS}}}summary").text = cdata(description)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(rss)
    tree.write(output_file, encoding="utf-8", xml_declaration=True)
    logging.info("RSS-Feed erstellt: %s", output_file)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Apple Podcasts zu einem RSS-Feed aggregieren")
    parser.add_argument("--term", default="bitcoin", help="Suchbegriff")
    parser.add_argument("--country", default="de", help="iTunes-Ländercode")
    parser.add_argument("--limit", type=int, default=100, help="Maximale Anzahl Podcasts")
    parser.add_argument("--output", type=Path, default=Path("docs/bitcoin_latest_episodes.xml"))
    parser.add_argument("--self-link", default="https://indyjudobusker.github.io/bitcoin-podcasts/bitcoin_latest_episodes.xml")
    parser.add_argument("--feed-image", default="https://indyjudobusker.github.io/bitcoin-podcasts/btc-feeda-aggr.png")
    parser.add_argument("--workers", type=int, default=5, help="Parallele Downloads")
    parser.add_argument("-v", "--verbose", action="store_true", help="Mehr Details")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logging.info(" Suche Podcasts …")
    feed_urls = search_podcasts(args.term, args.country, args.limit)
    logging.info("Gefundene Podcasts: %d", len(feed_urls))

    episodes: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_to_url = {
            executor.submit(get_latest_episode, url): url for url in feed_urls
        }
        for future in as_completed(future_to_url):
            try:
                episode = future.result()
                if episode and episode.get("audio_url"):
                    episodes.append(episode)
            except Exception as exc:
                logging.error("Fehler bei %s: %s", future_to_url[future], exc)

    logging.info("🎧 Episoden gesammelt: %d", len(episodes))
    generate_rss(episodes, args.output, args.self_link, args.feed_image)
    logging.info("✅ Fertig")


if __name__ == "__main__":
    main()
