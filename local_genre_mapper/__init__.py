#!/usr/bin/python

import re
from picard.metadata import register_track_metadata_processor

PLUGIN_NAME = "Local Genre Mapper"
PLUGIN_AUTHOR = "JamN3k"
PLUGIN_DESCRIPTION = """
Maps local genres using regex rules.
"""
PLUGIN_VERSION = "0.4"
PLUGIN_API_VERSIONS = ["2.0"]

GENRE_MAP = [

    # -------------------------
    # DOUJIN (very high priority)
    # -------------------------
    (r"同人.*", "doujin"),
    (r".*doujin.*", "doujin"),
    (r".*東方.*", "doujin"),

    # -------------------------
    # DIRECT LABELS
    # -------------------------
    (r"\bCutesy\b", "Cute"),
    (r"\bUtaite\b", "Cover"),

    (r"Rock & Roll", "Rock'n Roll"),
    (r"エレクトロニック", "EDM"),
    (r"Streetpunk", "Punk"),
    (r"Soul and Reggae", "Soul"),
    (r"\bAor\b", "Rock"),
    (r"Pop And Chart", "Pop"),
    (r"Drum and Bass", "DnB"),
    (r"Drumstep", "DnB"),
    (r"Mediaevil", "Medieval"),

    # -------------------------
    # METAL FAMILY (specific → broad inside metal)
    # -------------------------
    (r"Neo.*classical Metal", "Metal"),
    (r"German Metal", "Metal"),
    (r"Melodic Metal", "Metal"),
    (r"Alternative Metal", "Metal"),
    (r"British Metal", "Metal"),
    (r"Extreme Metal", "Metal"),

    (r"Power Metal", "Power Metal"),
    (r"Epic Metal", "Power Metal"),
    (r"Death Metal", "Death Metal"),
    (r"Thrash.*", "Thrash Metal"),
    (r"Metalcore", "Metalcore"),
    (r"Heavy Metal", "Metal"),
    (r".*Folk Metal", "Folk Metal"),

    (r".*honic Rock", "Symphonic Metal"),
    (r".*honic", "Symphonic Metal"),
    (r"Symphonic Metal", "Symphonic Metal"),

    # -------------------------
    # INSTRUMENTAL / ATMOSPHERIC
    # -------------------------
    (r".*Instrumental.*", "Instrumental"),
    (r".*Orchestra.*", "Instrumental"),
    (r"Chill.*", "Chill"),

    # -------------------------
    # ANIME / MEDIA FRANCHISE
    # -------------------------
    (r"Anime Music", "Anime"),
    (r"Pokemon", "Anime"),
    (r"Angel Beats", "Anime"),
    (r"Spice and Wolf", "Anime"),
    (r"Bakemonogatari", "Anime"),
    (r"Evangelion", "Anime"),
    (r"Bebop", "Anime"),

    # -------------------------
    # SOUNDTRACK / MEDIA
    # -------------------------
    (r".*Game.*", "Soundtrack"),
    (r".*Gaming.*", "Soundtrack"),
    (r".*Film.*", "Soundtrack"),
    (r"\bVgm\b", "Soundtrack"),
    (r".*Movie.*", "Soundtrack"),
    (r".*Television.*", "Soundtrack"),
    (r".*TV.*", "Soundtrack"),
    (r".*Podcast.*", "Soundtrack"),
    (r".*TTRPG.*", "Soundtrack"),
    (r".*Score.*", "Soundtrack"),
    (r".*OST.*", "Soundtrack"),
    (r".*Theme.*", "Soundtrack"),

    # -------------------------
    # VTUBER
    # -------------------------
    (r"Hololive", "VTuber"),
    (r".*Vtuber.*", "VTuber"),
    (r".*Virtual Youtuber.*", "VTuber"),

    # -------------------------
    # IDOL / POP SUBCULTURE
    # -------------------------
    (r".*Japanese Teen Pop.*", "Idol Pop"),
    (r".*idol.*", "Idol Pop"),

    # -------------------------
    # CORE GENRES
    # -------------------------
    (r".*Trap", "Trap"),
    (r".*\sPunk", "Punk"),
    (r".*Jazz", "Jazz"),
    (r".*Funk", "Funk"),
    (r".*Rock", "Rock"),
    (r".*Dubstep", "Dubstep"),
    (r".*House", "House"),
    (r".*Disco", "Disco"),
    (r".*Groov.*", "Groove"),
    (r".*Future Bass", "Future Bass"),
    (r".*\sRap", "Rap"),
    (r".*Indie", "Indie"),
    (r".*R&B", "R&B"),
    (r".*Dance", "Dance"),
    (r".*Jungle", "Jungle"),
    (r".*Hardcore", "Hardcore"),
    (r".*Blues", "Blues"),
    (r".*Hip[\s-]?Hop", "Hip Hop"),
    (r".*Bass", "DnB"),
    (r".*Country.*", "Country"),

    # -------------------------
    # ELECTRO SWING
    # -------------------------
    (r"Electro.*swing", "Electro Swing"),

    # -------------------------
    # FOLK FAMILY
    # -------------------------
    (r"Celtic", "Folk"),
    (r"Slavic", "Folk"),
    (r".*Folk", "Folk"),

    # -------------------------
    # POP FAMILY (lowest priority)
    # -------------------------
    (r".*J[\s-]?Pop", "J Pop"),
    (r".*K[\s-]?Pop", "K Pop"),
    (r".*City Pop", "City Pop"),
    (r".*Pop.*", "Pop"),

    (r".*[EÉ]lectro.*", "EDM"),

]

COMPILED_MAP = [
    (re.compile(pattern, re.IGNORECASE), replacement)
    for pattern, replacement in GENRE_MAP
]

GENRE_SPLIT_PATTERN = re.compile(r"[\/;,]")


def process_genres(album, metadata, track, release):
    genres = metadata.getall("genre")

    if not genres:
        return

    new_genres = []

    for genre in genres:
        for normalized_genre in [g.strip() for g in GENRE_SPLIT_PATTERN.split(genre) if g.strip()]:
            mapped = normalized_genre.strip()

            for regex, replacement in COMPILED_MAP:

                if regex.search(normalized_genre):
                    mapped = replacement
                    break

            if mapped not in new_genres:
                new_genres.append(mapped)

    metadata["genre"] = new_genres
    metadata["genre_o"] = genres


register_track_metadata_processor(process_genres, priority=9999)
