#!/usr/bin/python

import unicodedata
import re
from picard.metadata import register_track_metadata_processor
from picard import log
import json
from pathlib import Path

PLUGIN_NAME = "Local Genre Mapper"
PLUGIN_AUTHOR = "JamN3k"
PLUGIN_DESCRIPTION = """
Maps local genres using regex rules to
fix up genre tags from my collection to suit my personal taste.
"""
PLUGIN_VERSION = "0.12.2"
PLUGIN_API_VERSIONS = ["2.0"]
LASTFM_API_KEY = "98654a91f7e96b224e736286f6b87d03"
DISCOGS_TOKEN = "pprxQQlOmJloOlUiZKgqNyOvoUnwOoZDQQVEWRKZ"
GENRE_SPLIT_PATTERN = re.compile(r"[\/;,]")

DISCOGS_CACHE_KEY = "discorgs_track"
LASTFM_TRACK_CACHE_KEY = "lastfm_track"
LASTFM_ARTIST_CACHE_KEY = "lastfm_artist"

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
    if isinstance(genres, str):
        genres = [genres]

    flat_list = []
    for genre in genres:
        flat_list += [g.strip().lower() for g in GENRE_SPLIT_PATTERN.split(genre) if g.strip()]

    return list(set(flat_list))


def normalize_name(s):
    s = re.sub(r'[\*;<>"|?]_', '_', s.lower())
    s = unicodedata.normalize("NFKC", s)
    return s.lower()


def fast_map_genres(genres, g_prefix):
    new_genres = []

    # log.debug(f"Mapping: {genres}")

    if not genres:
        return []

    flat_list = flatten_list(genres)
    # log.warning(f"filters: {FILTER_LIST}")
    for genre in flat_list:
        # log.warning(f"genre {genre}")
        if any(regex.search(genre) for regex in FILTER_LIST):
            # log.warning(f"filter match {genre}")
            continue
        # log.warning(f"going with {genre}")
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

    # log.info(f"Mapped to: {new_genres}")

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
    album_files = album.tagger.get_files_from_objects([album])
    track_title = metadata.get("title", "")
    g_prefix = get_genre_prefix(metadata)

    discogs_cache = []
    lastfm_artist_cache = []
    lastfm_track_cache = []
    manual_genres = []

    file = next((file for file in album_files if file.metadata.get("title") == track_title), None)
    if file is not None:
        discogs_cache = fast_map_genres(file.metadata.get(DISCOGS_CACHE_KEY) or [], g_prefix)
        lastfm_artist_cache = fast_map_genres(file.metadata.get(LASTFM_ARTIST_CACHE_KEY) or [], g_prefix)
        lastfm_track_cache = fast_map_genres(file.metadata.get(LASTFM_TRACK_CACHE_KEY) or [], g_prefix)
        manual_genres = fast_map_genres(file.metadata.get("m_genre") or [], g_prefix)

    genres = metadata.getall("genre")
    log.warning(f"manual: {manual_genres}")
    genres = genres + manual_genres
    album_artist = metadata.get("albumartist", "")

    fast_genres = fast_map_genres(genres, g_prefix)

    if file is None:
        _finalize_genres(metadata, fast_genres)
        # log.debug(f"<{track_title}> not found in {album_filenames} - skipping")
        return

    # we have less than 3 genres, we should add more
    if len(fast_genres) < 4:
        # log.info(f"Insufficient tags: {fast_genres}")
        _fetch_lastfm_track_tags(album, metadata, album_artist, track_title,
                                 fast_genres, g_prefix, lastfm_artist_cache,
                                 discogs_cache, lastfm_track_cache)
        return

    # log.info(f"Sufficient tags: {fast_genres}")
    _finalize_genres(metadata, fast_genres)
    # log.debug(f"og genres: {genres}")


def _fetch_lastfm_track_tags(album, metadata, album_artist, track_title,
                             fast_genres, g_prefix, lastfm_artist_cache,
                             discogs_cache, lastfm_track_cache):
    log.debug(f"[LASTFM_T] Got cache: {lastfm_track_cache}")

    if any(lastfm_track_cache):
        extra = lastfm_track_cache
        fast_genres = fast_map_genres(fast_genres + extra, g_prefix)
        if len(fast_genres) < 4:
            _fetch_discogs_tags(album, metadata, album_artist, track_title,
                                fast_genres, g_prefix, lastfm_artist_cache,
                                discogs_cache)
            return

        _finalize_genres(metadata, fast_genres)
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

                    log.debug(f"[LASTFM_T] Got new: {extra}")
                    metadata[LASTFM_TRACK_CACHE_KEY] = extra
                    # log.info(f"Track tags for  {album_artist} - {track_title}: {extra}")
                    log.debug(f"[LASTFM_T] Got old: {fast_genres}")

                    enriched = fast_map_genres(fast_genres + extra, g_prefix)
                    if len(fast_genres) < 4:
                        _fetch_discogs_tags(album, metadata, album_artist,
                                            track_title, enriched, g_prefix,
                                            lastfm_artist_cache, discogs_cache)
                        return

                    _finalize_genres(metadata, enriched)
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


def _fetch_discogs_tags(album, metadata, album_artist, track_title,
                        fast_genres, g_prefix, lastfm_artist_cache,
                        discogs_cache):
    log.debug(f"[DISCORGS] Got cache: {discogs_cache}")

    if any(discogs_cache):
        extra = discogs_cache
        fast_genres = fast_map_genres(fast_genres + extra, g_prefix)
        if len(fast_genres) < 4:
            _fetch_lastfm_artist_tags(album, metadata, album_artist,
                                      track_title, fast_genres, g_prefix,
                                      lastfm_artist_cache)
            return

        _finalize_genres(metadata, fast_genres)
        return
    else:
        album._requests += 1

        def handle_response(response, reply, error):
            try:
                if not error:
                    results = response.get("results", [])
                    if not results:
                        log.warning("No Discogs matches")
                        extra = []
                    else:
                        item = results[0]

                        extra = (item.get("genre", []) or []) + (item.get("style", []) or [])
                        metadata[DISCOGS_CACHE_KEY] = extra

                    enriched = fast_map_genres(fast_genres + extra, g_prefix)
                    if len(enriched) < 4:
                        _fetch_lastfm_artist_tags(album, metadata,
                                                  album_artist, track_title,
                                                  enriched, g_prefix,
                                                  lastfm_artist_cache)
                        return

                    _finalize_genres(metadata, enriched)
            except Exception as e:
                log.debug(f"Discogs response error: {e}")
            finally:
                album._requests -= 1
                if not album._requests:
                    album._finalize_loading(None)

        album.tagger.webservice.get_url(
            url="https://api.discogs.com/database/search",
            handler=handle_response,
            parse_response_type="json",
            priority=False,
            important=False,
            queryargs={
                "artist": album_artist,
                "track": track_title,
                "type": "release",
                "token": DISCOGS_TOKEN,
            }
        )


def _fetch_lastfm_artist_tags(album, metadata, album_artist, track_title,
                              fast_genres, g_prefix, lastfm_artist_cache):
    log.debug(f"[LASTFM_A] Got cache: {lastfm_artist_cache}")

    if any(lastfm_artist_cache):
        # Already cached — use immediately
        extra = lastfm_artist_cache
        fast_genres = fast_map_genres(fast_genres + extra, g_prefix)
        _finalize_genres(metadata, fast_genres)
        return
    else:
        album._requests += 1

        def handle_artist_response(response, reply, error):
            try:
                if not error:
                    tags = response.get("toptags", {}).get("tag", [])
                    # log.warning(f"Artist tags: {tags}")
                    tags = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)[:3]
                    extra = [t["name"] for t in tags]
                    metadata[LASTFM_ARTIST_CACHE_KEY] = extra
                    # log.info(f"Artist tags for  {album_artist}: {extra}")
                    if not extra:
                        log.warning(f"No artist tags on last.fm for {album_artist}")
                    enriched = fast_map_genres(fast_genres + extra, g_prefix)
                    _finalize_genres(metadata, enriched)
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
    log.debug(f"Final: {genres}")
    deduped = list(set(genres))
    final = []
    for genre in deduped:
        pattern = re.compile(rf'\b{re.escape(genre)}\b$', re.IGNORECASE)
        if not any(item for item in deduped if pattern.search(item) and item != genre):
            final.append(genre)

    final.sort()
    if len(final) == 0:
        del metadata["genre"]
        return

    metadata["genre"] = final


register_track_metadata_processor(process_genres, priority=9999)
