#!/usr/bin/env python3
import requests
import feedparser
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import format_datetime

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ATOM_NS = "http://www.w3.org/2005/Atom"
MEDIA_NS = "http://search.yahoo.com/mrss/"

ET.register_namespace("itunes", ITUNES_NS)
ET.register_namespace("atom", ATOM_NS)
ET.register_namespace("media", MEDIA_NS)

def cdata(text):
    return f"<![CDATA[{text}]]>"

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

    # Episodenbild (falls vorhanden)
    episode_image = None
    if "image" in entry:
        episode_image = entry.image.get("href")
    elif "itunes_image" in entry:
        episode_image = entry.itunes_image.get("href")
    elif "itunes_image" in feed.feed:  # fallback auf Podcast-Bild
        episode_image = feed.feed.itunes_image.get("href")

    # Beschreibung
    # content:encoded (meist am ausführlichsten)
    if "content" in entry and entry.content:
        episode_description = entry.content[0].value
    # itunes:summary
    elif "itunes_summary" in entry:
       episode_description = entry.itunes_summary
    # 3. description
    elif "description" in entry:
        episode_description = entry.description
    # 4. summary
    elif "summary" in entry:
        episode_description = entry.summary

    duration = getattr(entry, "itunes_duration", None)
    
    print(f"   ✔ Neueste Folge: {entry.get('title', 'Unbekannter Titel')}\n")

    return {
        "podcast_title": podcast_title,
        "episode_title": entry.get("title", "Unbekannte Folge"),
        "link": entry.get("link", ""),
        "published": entry.get("published_parsed"),
        "audio_url": enclosure_url,
        "audio_length": enclosure_length,
        "guid": entry.get("id", entry.get("link", "")),
        "episode_image": episode_image,
        "episode_description": episode_description,
        "duration": duration,
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

    ET.SubElement(channel,f"{{{ITUNES_NS}}}image",href="https://indyjudobusker.github.io/bitcoin-podcasts/btc-feeda-aggr.png")

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

        if ep["episode_image"]:
            #ET.SubElement(item, "itunes:image", href=ep["episode_image"])
            ET.SubElement(
                item,
                f"{{{ITUNES_NS}}}image",
                href=ep["episode_image"],
            )

            ET.SubElement(
                item,
                f"{{{MEDIA_NS}}}thumbnail",
                url=ep["episode_image"],
            )

            ET.SubElement(
                item,
                f"{{{MEDIA_NS}}}content",
                url=ep["episode_image"],
                medium="image",
                type="image/jpeg",
            )

        if ep["audio_url"]:
            ET.SubElement(
                item,
                "enclosure",
                url=ep["audio_url"],
                length=str(ep["audio_length"]),
                type="audio/mpeg",
            )

        if ep.get("duration"):
            ET.SubElement(item, f"{{{ITUNES_NS}}}duration").text = ep["duration"]
        
        description = ep.get("episode_description", "").strip()

        if description:
            # Standard RSS
            ET.SubElement(item, "description").text = cdata(description)

            # Apple Podcasts
            ET.SubElement(
                item,
                f"{{{ITUNES_NS}}}summary"
            ).text = cdata(description)


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

