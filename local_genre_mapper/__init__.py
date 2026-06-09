#!/usr/bin/python

import re
from picard.metadata import register_track_metadata_processor
from picard import log
import json
from pathlib import Path
from picard.webservice import ratecontrol

PLUGIN_NAME = "Local Genre Mapper"
PLUGIN_AUTHOR = "JamN3k"
PLUGIN_DESCRIPTION = """
Maps local genres using regex rules to
fix up genre tags from my collection to suit my personal taste.
"""
PLUGIN_VERSION = "0.10.0"
PLUGIN_API_VERSIONS = ["2.0"]
LASTFM_API_KEY = "98654a91f7e96b224e736286f6b87d03"

GENRE_SPLIT_PATTERN = re.compile(r"[\/;,]")

WIKIDATA_HOST = 'www.wikidata.org'
WIKIDATA_PORT = 443

ratecontrol.set_minimum_delay((WIKIDATA_HOST, WIKIDATA_PORT), 0)

WIKIDATA_CACHE = {}
LASTFM_CACHE = {}


# load resources
path = f'{Path(__file__).parent}/genre_map.json'
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

COMPILED_MAP = [
    (re.compile(pattern, re.IGNORECASE), target_genre)
    for pattern, target_genre in data
]

path = Path(__file__).parent / "filter_list.json"
with open(path, "r", encoding="utf-8") as f:
    patterns = json.load(f)

FILTER_LIST = [re.compile(p, re.IGNORECASE) for p in patterns]


def flatten_list(genres):
    flat_list = []
    for genre in genres:
        flat_list += [g.strip().lower() for g in GENRE_SPLIT_PATTERN.split(genre) if g.strip()]

    return list(set(flat_list))


def fast_map_genres(genres, g_prefix):
    new_genres = []

    if not genres:
        return []

    flat_list = flatten_list(genres)

    for genre in flat_list:
        if any(regex.search(genre) for regex in FILTER_LIST):
            continue
        mapped = genre

        for regex, replacement in COMPILED_MAP:
            if regex.search(mapped):
                mapped = replacement
                break

        split_mapped = GENRE_SPLIT_PATTERN.split(mapped)
        for split_genre in split_mapped:
            if g_prefix is not None:
                if split_genre.lower() == "rock":
                    split_genre = f"{g_prefix} rock"

                if split_genre.lower() == "pop":
                    split_genre = f"{g_prefix} pop"

            if split_genre not in new_genres:
                new_genres.append(split_genre.lower())

    return new_genres


def get_genre_prefix(metadata):
    language = metadata.get("~releaselanguage")
    if language == "jpn":
        return "j"

    language = metadata.get("language")
    if language == "jpn":
        return "j"

    script = metadata.get("script")
    if script == "Jpan":
        return "j"
    if script == "Kore":
        return "k"

    return None


def process_genres(album, metadata, track, release):
    album_filenames = album.tagger.get_files_from_objects([album])

    genres = metadata.getall("genre")
    album_artist = metadata.get("albumartist", "")
    track_title = metadata.get("title", "")
    g_prefix = get_genre_prefix(metadata)

    fast_genres = fast_map_genres(genres, g_prefix)

    # Skip tracks which don't exist in local files
    normalized_name = re.sub(r'[\*;<>"|?]_', '_', track_title.lower())
    if not any(normalized_name in str(filename).lower() for filename in album_filenames):
        _finalize_genres(metadata, fast_genres)
        log.debug(f"og genres: {genres}")
        log.debug(f"<{track_title}> not found in {album_filenames} - skipping")
        return

    # we have less than 3 genres, we should add more
    if len(fast_genres) < 3:
        _fetch_track_tags(album, metadata, album_artist, track_title, genres, fast_genres, g_prefix)
        return

    # there's 3+ genres
    _finalize_genres(metadata, fast_genres)
    log.debug(f"og genres: {genres}")


def _fetch_track_tags(album, metadata, album_artist,
                      track_title, genres, fast_genres, g_prefix):
    key = (album_artist, track_title)

    if key in LASTFM_CACHE:
        # Already cached — use immediately
        extra = LASTFM_CACHE[key]
        fast_genres = fast_map_genres(fast_genres + extra, g_prefix)
        _finalize_genres(metadata, fast_genres)
        log.debug(f"og genres: {genres+extra}")
        return
    else:
        # Kick off async request, hold finalization open
        album._requests += 1

        def handle_response(response, reply, error):
            try:
                if not error:
                    tags = response.get("toptags", {}).get("tag", [])
                    tags = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)[:3]
                    extra = [t["name"] for t in tags]

                    if not extra:
                        # Fall back to artist tags
                        log.warning(f"No track tags on last.fm for {album_artist} - {track_title}")
                        _fetch_artist_tags(album, metadata, album_artist,
                                           genres, fast_genres, g_prefix)
                        return

                    LASTFM_CACHE[key] = extra
                    enriched = fast_map_genres(fast_genres + extra, g_prefix)
                    _finalize_genres(metadata, enriched)
                    log.debug(f"og genres: {genres+extra}")
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


def _fetch_artist_tags(album, metadata, album_artist,
                       genres, fast_genres, g_prefix):
    key = ("artist", album_artist)
    album._requests += 1

    def handle_artist_response(response, reply, error):
        try:
            if not error:
                tags = response.get("toptags", {}).get("tag", [])
                log.warning(f"Artist tags: {tags}")
                tags = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)[:3]
                extra = [t["name"] for t in tags]
                if not extra:
                    log.warning(f"No artist tags on last.fm for {album_artist}")
                LASTFM_CACHE[key] = extra
                enriched = fast_map_genres(fast_genres + extra, g_prefix)
                _finalize_genres(metadata, enriched)
                log.debug(f"og genres: {genres+extra}")
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


def _finalize_genres(metadata, genres):
    deduped = list(set(genres))
    final = []
    for genre in deduped:
        pattern = re.compile(rf'\b{re.escape(genre)}\b$', re.IGNORECASE)
        if not any(item for item in deduped if pattern.search(item) and item != genre):
            final.append(genre)

    final.sort()
    metadata["genre"] = final


register_track_metadata_processor(process_genres, priority=9999)
