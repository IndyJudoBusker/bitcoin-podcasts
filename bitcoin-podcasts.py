#!/usr/bin/env python3
import requests
import feedparser
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import format_datetime

SEARCH_TERM = "bitcoin"
COUNTRY = "de"
LIMIT = 100
OUTPUT_FILE = "docs/bitcoin_latest_episodes.xml"
#OUTPUT_FILE = "bitcoin_latest_episodes.xml"

# --------------------------------------------------
# Schritt 1: Apple Podcasts durchsuchen
# --------------------------------------------------
def search_podcasts(term, country="de", limit=100):
    url = "https://itunes.apple.com/search"
    params = {
        "term": term,
        "entity": "podcast",
        "country": country,
        "limit": limit,
    }
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    return [r["feedUrl"] for r in data.get("results", []) if "feedUrl" in r]


# --------------------------------------------------
# Schritt 2 & 3: Neueste Folge aus jedem RSS-Feed holen
# --------------------------------------------------
#def get_latest_episode(feed_url):
#    feed = feedparser.parse(feed_url)
#
#    if not feed.entries:
#        return None
#
#    entry = feed.entries[0]  # neueste Episode
#
#    enclosure_url = None
#    enclosure_length = None
#    if "enclosures" in entry and entry.enclosures:
#        enclosure_url = entry.enclosures[0].get("href")
#        enclosure_length = entry.enclosures[0].get("length", "0")
#
#    return {
#        "podcast_title": feed.feed.get("title", "Unbekannter Podcast"),
#        "episode_title": entry.get("title", "Unbekannte Folge"),
#        "link": entry.get("link", ""),
#        "published": entry.get("published_parsed"),
#        "audio_url": enclosure_url,
#        "audio_length": enclosure_length,
#        "guid": entry.get("id", entry.get("link", "")),
#    }
def get_latest_episode(feed_url):
    print(f"➡️  Lade Feed: {feed_url}")

    feed = feedparser.parse(feed_url)

    podcast_title = feed.feed.get("title", feed_url)
    print(f"   🎙 Podcast: {podcast_title}")

    if not feed.entries:
        print("   ⚠️ Keine Episoden gefunden\n")
        return None

    entry = feed.entries[0]  # neueste Episode

    enclosure_url = None
    enclosure_length = None
    if "enclosures" in entry and entry.enclosures:
        enclosure_url = entry.enclosures[0].get("href")
        enclosure_length = entry.enclosures[0].get("length", "0")

    if not enclosure_url:
        print("   ⚠️ Keine Audio-Datei (enclosure) gefunden\n")
        return None

    print(f"   ✔ Neueste Folge: {entry.get('title', 'Unbekannter Titel')}\n")

    return {
        "podcast_title": podcast_title,
        "episode_title": entry.get("title", "Unbekannte Folge"),
        "link": entry.get("link", ""),
        "published": entry.get("published_parsed"),
        "audio_url": enclosure_url,
        "audio_length": enclosure_length,
        "guid": entry.get("id", entry.get("link", "")),
    }



# --------------------------------------------------
# Schritt 4: Gemeinsamen RSS-Feed erzeugen
# --------------------------------------------------
def generate_rss(episodes, output_file):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = "Bitcoin – Aktuelle Podcast-Folgen"
    ET.SubElement(channel, "link").text = "https://example.com/bitcoin-podcast-feed"
    ET.SubElement(channel, "description").text = (
        "Die jeweils neueste Folge aller Apple-Podcasts zum Thema Bitcoin"
    )
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.utcnow())

    for ep in episodes:
        item = ET.SubElement(channel, "item")

        ET.SubElement(
            item, "title"
        ).text = f"{ep['podcast_title']} – {ep['episode_title']}"
        ET.SubElement(item, "link").text = ep["link"]
        ET.SubElement(item, "guid").text = ep["guid"]

        if ep["published"]:
            pub_date = datetime(*ep["published"][:6])
            ET.SubElement(item, "pubDate").text = format_datetime(pub_date)

        if ep["audio_url"]:
            ET.SubElement(
                item,
                "enclosure",
                url=ep["audio_url"],
                length=str(ep["audio_length"]),
                type="audio/mpeg",
            )

    tree = ET.ElementTree(rss)
    tree.write(output_file, encoding="utf-8", xml_declaration=True)


# --------------------------------------------------
# Main
# --------------------------------------------------
def main():
    print("🔎 Suche Podcasts …")
    feed_urls = search_podcasts(SEARCH_TERM, COUNTRY, LIMIT)
    print(f"Gefundene Podcasts: {len(feed_urls)}")

    episodes = []
    for url in feed_urls:
        try:
            episode = get_latest_episode(url)
            if episode and episode["audio_url"]:
                episodes.append(episode)
        except Exception as e:
            print(f"⚠️ Fehler bei {url}: {e}")

    print(f"🎧 Episoden gesammelt: {len(episodes)}")
    generate_rss(episodes, OUTPUT_FILE)
    print(f"✅ RSS-Feed erstellt: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

