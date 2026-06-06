#!/usr/bin/python

import re
from picard.metadata import register_track_metadata_processor
from picard import log
import json
from pathlib import Path
import threading
import queue

PLUGIN_NAME = "Local Genre Mapper"
PLUGIN_AUTHOR = "JamN3k"
PLUGIN_DESCRIPTION = """
Maps local genres using regex rules to
fix up genre tags from my collection to suit my personal taste.
"""
PLUGIN_VERSION = "0.7.3"
PLUGIN_API_VERSIONS = ["2.0"]
LASTFM_API_KEY = "98654a91f7e96b224e736286f6b87d03"

GENRE_SPLIT_PATTERN = re.compile(r"[\/;,]")

LASTFM_CACHE = {}
ENRICHMENT_CACHE = {}
PENDING_REQUESTS = set()
LOCK = threading.Lock()

LASTFM_QUEUE = queue.Queue()
LASTFM_RESULTS = {}


def load_genre_map():
    path = f'{Path(__file__).parent}/genre_map.json'
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return [
        (re.compile(pattern, re.IGNORECASE), target_genre)
        for pattern, target_genre in raw
    ]


COMPILED_MAP = load_genre_map()


def load_filter_list():
    path = Path(__file__).parent / "filter_list.json"
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    return raw


FILTER_LIST = load_filter_list()


def fast_map_genres(genres):
    new_genres = []

    for genre in genres:
        parts = [g.strip().lower() for g in GENRE_SPLIT_PATTERN.split(genre) if g.strip()]

        for part in parts:
            mapped = part

            for regex, replacement in COMPILED_MAP:
                if regex.search(part):
                    mapped = replacement
                    break

            if mapped not in new_genres:
                new_genres.append(mapped.lower())

    return new_genres


def process_genres(album, metadata, track, release):
    album_filenames = album.tagger.get_files_from_objects([album])
    log.warning(album_filenames)

    return

    genres = metadata.getall("genre")
    album_artist = metadata.get("albumartist", "")
    track_title = metadata.get("title", "")

    fast_genres = fast_map_genres(genres)

    if len(fast_genres) < 3:
        key = (album_artist, track_title)

        if key in LASTFM_CACHE:
            # Already cached — use immediately
            extra = LASTFM_CACHE[key]
            fast_genres = fast_map_genres(fast_genres + extra)
            _finalize_genres(metadata, fast_genres, genres + extra)
        else:
            # Kick off async request, hold finalization open
            album._requests += 1
            _finalize_genres(metadata, fast_genres, genres)  # write what we have now

            def handle_response(response, reply, error):
                try:
                    if not error:
                        tags = response.get("toptags", {}).get("tag", [])
                        tags = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)[:4]
                        extra = [t["name"] for t in tags]

                        if not extra:
                            # Fall back to artist tags
                            _fetch_artist_tags(album, metadata, album_artist, genres, fast_genres)
                            return

                        LASTFM_CACHE[key] = extra
                        enriched = fast_map_genres(fast_genres + extra)
                        _finalize_genres(metadata, enriched, genres + extra)
                except Exception as e:
                    log.debug(f"Last.fm response error: {e}")
                finally:
                    album._requests -= 1
                    if not album._requests:
                        album._finalize_loading(None)

            album.tagger.webservice.get_url(
                url="https://ws.audioscrobbler.com/2.0/",
                handler=handle_response,
                parse_response_type="json",
                priority=False,
                important=False,
                queryargs={
                    "method": "track.getTopTags",
                    "artist": album_artist,
                    "track": track_title,
                    "api_key": LASTFM_API_KEY,
                    "format": "json",
                }
            )
            return
    _finalize_genres(metadata, fast_genres, genres)


def _fetch_artist_tags(album, metadata, album_artist, genres, fast_genres):
    key = ("artist", album_artist)
    album._requests += 1

    def handle_artist_response(response, reply, error):
        try:
            if not error:
                tags = response.get("toptags", {}).get("tag", [])
                tags = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)[:4]
                extra = [t["name"] for t in tags]
                LASTFM_CACHE[key] = extra
                enriched = fast_map_genres(fast_genres + extra)
                _finalize_genres(metadata, enriched, genres)
        except Exception as e:
            log.debug(f"Last.fm artist response error: {e}")
        finally:
            album._requests -= 1
            if not album._requests:
                album._finalize_loading(None)

    album.tagger.webservice.get_url(
        url="https://ws.audioscrobbler.com/2.0/",
        handler=handle_artist_response,
        parse_response_type="json",
        priority=False,
        important=False,
        queryargs={
            "method": "artist.getTopTags",
            "artist": album_artist,
            "api_key": LASTFM_API_KEY,
            "format": "json",
        }
    )


def _finalize_genres(metadata, fast_genres, original_genres):
    final = []
    for g in fast_genres:
        if g not in FILTER_LIST and g not in final:
            final.append(g)
    metadata["genre"] = final
    metadata["genre_o"] = original_genres


register_track_metadata_processor(process_genres, priority=9999)
