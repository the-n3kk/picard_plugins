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
MANUAL_GENRES_KEY = "manual_genres"

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

    # log.info(f"Mapping: {genres}")

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

    new_genres.sort()
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


def get_alias(obj):
    aliases = obj["aliases"]

    if not any(aliases):
        return None

    result = next((alias for alias in aliases if alias["locale"] == "en"), None)

    # IF there's no EN specific alias perhaps there's a generic fallback?
    if result is None:
        result = next((alias for alias in aliases), None)

    log.warning(f"[ALIASES] Got alias: {result}")
    return result


def contains_non_latin(text):
    return bool(re.search(r"[^A-Za-z0-9\s.,;:!?'\-()]", text))


def preprocess_track(track, release, metadata):
    if contains_non_latin(metadata.get("title")):
        track_alias = get_alias(track["recording"])
        log.info(f"[PREPROCESS] {metadata.get("title")} -> {track_alias}")
        if track_alias is not None:
            metadata["title"] = track_alias["name"]

    if contains_non_latin(metadata.get("album")):
        album_alias = get_alias(release)
        log.info(f"[PREPROCESS] {metadata.get("album")} -> {album_alias}")
        if album_alias is not None:
            metadata["album"] = album_alias["name"]

    album_artist = metadata.get("albumartist")
    album_artist_so = metadata.get("albumartistsort")
    artists = metadata.get("artists")
    artists_so = metadata.get("artistsort")

    artist_credits = track["recording"]["artist-credit"]
    for artist_credit in artist_credits:
        artist_obj = artist_credit["artist"]
        artist_alias = get_alias(artist_obj)

        if artist_alias is None:
            continue

        og_name = artist_obj["name"]
        og_name_so = artist_obj["sort-name"]
        new_name = artist_alias["name"]
        new_name_so = artist_alias["sort-name"]

        if contains_non_latin(og_name):
            log.info(f"[PREPROCESS] grabbing aliases for {og_name}")
            album_artist = album_artist.replace(og_name, new_name)
            album_artist_so = album_artist_so.replace(og_name_so, new_name_so)

            artists = artists.replace(og_name, new_name)
            artists_so = artists_so.replace(og_name_so, new_name_so)

    metadata["albumartist"] = album_artist
    metadata["albumartistsort"] = album_artist_so
    metadata["artists"] = artists.split(";")
    metadata["artistsort"] = artists_so


def process_genres(album, metadata, track, release):

    album_files = album.tagger.get_files_from_objects([album])
    track_title = metadata.get("title", "")
    g_prefix = get_genre_prefix(metadata)

    file = next((file for file in album_files if file.metadata.get("title") == track_title), None)
    if file is not None:
        metadata[DISCOGS_CACHE_KEY] = fast_map_genres(file.metadata.get(DISCOGS_CACHE_KEY) or [], g_prefix)
        metadata[LASTFM_ARTIST_CACHE_KEY] = fast_map_genres(file.metadata.get(LASTFM_ARTIST_CACHE_KEY) or [], g_prefix)
        metadata[LASTFM_TRACK_CACHE_KEY] = fast_map_genres(file.metadata.get(LASTFM_TRACK_CACHE_KEY) or [], g_prefix)
        metadata[MANUAL_GENRES_KEY] = flatten_list(file.metadata.getall(MANUAL_GENRES_KEY) or [])
        preprocess_track(track, release, metadata)

    track_title = metadata.get("title", "")

    genres = metadata.getall("genre")
    album_artist = metadata.get("albumartist", "")

    fast_genres = fast_map_genres(genres, g_prefix)

    if file is None:
        log.info(f"<{track_title}> not found - skipping")
        _finalize_genres(metadata, fast_genres)
        return

    # we have less than 3 genres, we should add more
    if len(fast_genres) < 4:
        # log.info(f"Insufficient tags: {fast_genres}")
        _fetch_lastfm_track_tags(album, metadata, album_artist, track_title,
                                 fast_genres, g_prefix)
        return

    # log.info(f"Sufficient tags: {fast_genres}")
    _finalize_genres(metadata, fast_genres)
    # log.info(f"og genres: {genres}")


def _fetch_lastfm_track_tags(album, metadata, album_artist, track_title,
                             fast_genres, g_prefix):

    lastfm_track_cache = metadata.getall(LASTFM_TRACK_CACHE_KEY) or []
    log.info(f"[LASTFM_T] Got cache: {lastfm_track_cache}")

    if any(lastfm_track_cache):
        extra = lastfm_track_cache
        fast_genres = fast_map_genres(fast_genres + extra, g_prefix)
        if len(fast_genres) < 4:
            _fetch_discogs_tags(album, metadata, album_artist, track_title,
                                fast_genres, g_prefix)
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
                    if any(tags):
                        tags = sorted(tags, key=lambda t: int(t.get("count", 0)), reverse=True)[:3]
                        extra = [t["name"] for t in tags]

                        log.info(f"[LASTFM_T] Got new: {extra}")
                        metadata[LASTFM_TRACK_CACHE_KEY] = extra
                        # log.info(f"Track tags for  {album_artist} - {track_title}: {extra}")
                        log.info(f"[LASTFM_T] Got old: {fast_genres}")

                        enriched = fast_map_genres(fast_genres + extra, g_prefix)
                        if len(fast_genres) < 4:
                            _fetch_discogs_tags(album, metadata, album_artist,
                                                track_title, enriched, g_prefix)
                            return

                        _finalize_genres(metadata, enriched)
            except Exception as e:
                log.error(f"Last.fm response error: {e}")
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
                        fast_genres, g_prefix):

    discogs_cache = metadata.getall(DISCOGS_CACHE_KEY) or []
    log.info(f"[DISCORGS] Got cache: {discogs_cache}")

    if any(discogs_cache):
        fast_genres = fast_map_genres(fast_genres + discogs_cache, g_prefix)
        if len(fast_genres) < 4:
            _fetch_lastfm_artist_tags(album, metadata, album_artist,
                                      track_title, fast_genres, g_prefix)
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
                    else:
                        item = results[0]

                        extra = (item.get("genre", []) or []) + (item.get("style", []) or [])
                        metadata[DISCOGS_CACHE_KEY] = extra
                        enriched = fast_map_genres(fast_genres + extra, g_prefix)
                        if len(enriched) < 4:
                            _fetch_lastfm_artist_tags(album, metadata,
                                                      album_artist, track_title,
                                                      enriched, g_prefix)
                            return
                        _finalize_genres(metadata, enriched)
            except Exception as e:
                log.error(f"Discogs response error: {e}")
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
                              fast_genres, g_prefix):

    lastfm_artist_cache = metadata.getall(LASTFM_ARTIST_CACHE_KEY) or []
    log.info(f"[LASTFM_A] Got cache: {lastfm_artist_cache}")

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
                    if any(tags):
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
                log.error(f"Last.fm artist response error: {e}")
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
    manual = metadata.getall(MANUAL_GENRES_KEY)
    log.info(f"Final: {genres} and manual {manual}")

    for g in manual:
        gen_str = g[1:]
        if g.startswith("-"):
            log.info(f"[FINAL] Removing {gen_str}")
            if gen_str in genres:
                genres.remove(gen_str)
        else:
            log.info(f"[FINAL] Adding {g}")
            genres.append(g)

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

    log.info(f"[FINAL] Saving: {final}")
    metadata["genre"] = final
    metadata["testing"] = "xyz"


register_track_metadata_processor(process_genres, priority=9999)
