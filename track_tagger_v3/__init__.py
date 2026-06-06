#!/usr/bin/python

from picard.plugin3.api import PluginApi

import re
import json
from pathlib import Path
from functools import partial

LASTFM_API_KEY = "98654a91f7e96b224e736286f6b87d03"

GENRE_SPLIT_PATTERN = re.compile(r"[\/;,]")

LASTFM_CACHE = {}

FILTER_LIST = []
COMPILED_MAP = []


def load_genre_map():
    path = Path(__file__).parent / "genre_map.json"
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return [
        (re.compile(pattern, re.IGNORECASE), target_genre)
        for pattern, target_genre in raw
    ]


def load_filter_list():
    path = Path(__file__).parent / "filter_list.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


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


def _finalize_genres(metadata, fast_genres, original_genres):
    final = []
    for g in fast_genres:
        if g not in FILTER_LIST and g not in final:
            final.append(g)
    metadata["genre"] = final
    metadata["genre_o"] = original_genres


def _fetch_artist_tags(api, album, task_id, metadata, album_artist, genres, fast_genres):
    artist_key = ("artist", album_artist)

    if artist_key in LASTFM_CACHE:
        extra = LASTFM_CACHE[artist_key]
        enriched = fast_map_genres(fast_genres + extra)
        _finalize_genres(metadata, enriched, genres + extra)
        return

    artist_task_id = f"{task_id}_artist"

    def create_artist_request():
        return api.web_service.get_url(
            url="https://ws.audioscrobbler.com/2.0/",
            handler=partial(handle_artist_response, api, album, artist_task_id,
                            metadata, album_artist, genres, fast_genres),
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

    api.add_album_task(
        album, artist_task_id,
        f"Fetching Last.fm artist tags for {album_artist}",
        request_factory=create_artist_request
    )


def handle_artist_response(api, album, task_id, metadata, album_artist, genres, fast_genres,
                            data, error):
    try:
        if not error:
            tags = data.get("toptags", {}).get("tag", [])
            tags = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)[:4]
            extra = [t["name"] for t in tags]
            LASTFM_CACHE[("artist", album_artist)] = extra
            enriched = fast_map_genres(fast_genres + extra)
            _finalize_genres(metadata, enriched, genres + extra)
        else:
            api.logger.debug(f"Last.fm artist tags error for {album_artist}")
            _finalize_genres(metadata, fast_genres, genres)
    except Exception as e:
        api.logger.debug(f"Last.fm artist response error: {e}")
        _finalize_genres(metadata, fast_genres, genres)
    finally:
        api.complete_album_task(album, task_id)


def handle_track_response(api, album, task_id, metadata, album_artist, track_title,
                           genres, fast_genres, data, error):
    track_key = (album_artist, track_title)
    try:
        if not error:
            tags = data.get("toptags", {}).get("tag", [])
            tags = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)[:4]
            extra = [t["name"] for t in tags]

            if not extra:
                # Fall back to artist tags — complete this task first, artist fetch will add its own
                api.complete_album_task(album, task_id)
                _fetch_artist_tags(api, album, task_id, metadata, album_artist, genres, fast_genres)
                return

            LASTFM_CACHE[track_key] = extra
            enriched = fast_map_genres(fast_genres + extra)
            _finalize_genres(metadata, enriched, genres + extra)
        else:
            api.logger.debug(f"Last.fm track tags error for {album_artist} - {track_title}")
            _finalize_genres(metadata, fast_genres, genres)
    except Exception as e:
        api.logger.debug(f"Last.fm track response error: {e}")
        _finalize_genres(metadata, fast_genres, genres)
    finally:
        api.complete_album_task(album, task_id)


def process_genres(api, track, metadata, track_node, release_node):
    album = track.album
    album_artist = metadata.get("albumartist", "")
    track_title = metadata.get("title", "")
    genres = metadata.getall("genre")

    fast_genres = fast_map_genres(genres)

    if len(fast_genres) >= 3:
        # Enough genres already — finalize immediately, no web request needed
        _finalize_genres(metadata, fast_genres, genres)
        return

    track_key = (album_artist, track_title)

    if track_key in LASTFM_CACHE:
        extra = LASTFM_CACHE[track_key]
        enriched = fast_map_genres(fast_genres + extra)
        _finalize_genres(metadata, enriched, genres + extra)
        return

    # Sanitize track title for use in task ID
    safe_title = re.sub(r"[^a-zA-Z0-9_]", "_", track_title)[:40]
    task_id = f"lastfm_track_{album.id}_{safe_title}"

    def create_track_request():
        return api.web_service.get_url(
            url="https://ws.audioscrobbler.com/2.0/",
            handler=partial(handle_track_response, api, album, task_id,
                            metadata, album_artist, track_title,
                            genres, fast_genres),
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

    # Write what we have now so the track isn't left empty while waiting
    _finalize_genres(metadata, fast_genres, genres)

    api.add_album_task(
        album, task_id,
        f"Fetching Last.fm track tags for {track_title}",
        request_factory=create_track_request
    )


def enable(api: PluginApi):
    """Called when plugin is enabled."""
    global COMPILED_MAP, FILTER_LIST
    COMPILED_MAP = load_genre_map()
    FILTER_LIST = load_filter_list()
    api.register_track_metadata_processor(process_genres)
