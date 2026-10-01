"""Game identity keys used to group posts about the same game from different sources into one estate.

Two kinds of keys:
  * store keys — exact store identity: ``steam:2484180``, ``egs:mechabellum``, ``gog:...``, ``itch:...``
  * name keys  — compacted game name: ``name:astreasixsidedoracles``

Names come from store URL slugs, GameInfo names and Latin-script chunks of headlines
("Халява: в Steam раздача Deadshot" → "Deadshot").
"""

import re
from typing import Iterable, Optional
from urllib.parse import urlparse

# Minimal compact length for a name to be used as a key at all / for substring matching in titles
MIN_NAME_LEN = 4
MIN_SUBSTRING_LEN = 6

# Words stripped from the edges of a Latin chunk ("Epic Games Store Mechabellum" → "Mechabellum")
_EDGE_WORDS = {
    "steam", "epic", "games", "game", "store", "egs", "gog", "gogcom", "itch", "itchio", "pc",
    "giveaway", "free", "mobile", "android", "ios", "xbox", "playstation", "ps4", "ps5",
    "ubisoft", "connect", "ea", "amazon", "humble", "fanatical", "indiegala", "gamerpower", "dlc", "the",
}

# Whole chunks that are platforms/services, never game names
_GENERIC_CHUNKS = {
    "steam", "epicgames", "epicgamesstore", "egs", "gog", "gogcom", "itchio", "pc", "android", "ios",
    "xbox", "playstation", "psplus", "nintendo", "nintendoswitch", "switch", "giveaway", "free", "dlc",
    "rpg", "mmo", "mmorpg", "f2p", "ubisoft", "ubisoftconnect", "eaapp", "origin", "amazon",
    "primegaming", "amazonprimegaming", "humblebundle", "fanatical", "indiegala", "gamepass",
    "gamespass", "xboxgamepass", "xboxgamespass", "pcgamepass", "gamerpower", "steamdeck", "windows",
    "linux", "macos", "vr", "online", "update", "demo", "beta", "early access", "earlyaccess",
}

_GIVEAWAY_RE = re.compile(
    r"раздач|разда[юё]т|бесплатн|халяв|даром|забрать|забирайте|100\s*%|giveaway|\bfree\b|безкоштовн|роздач",
    re.IGNORECASE,
)

_MOBILE_RE = re.compile(r"\bandroid\b|\bios\b|смартфон|мобильн|мобільн|\(mobile\)", re.IGNORECASE)

_EGS_HASH_SUFFIX = re.compile(r"-[0-9a-f]{6}$")


def compact(text: str) -> str:
    """Lowercase and drop everything except letters/digits: 'Six-Sided Oracles' → 'sixsidedoracles'."""
    return re.sub(r"[\W_]+", "", (text or "").lower().replace("ё", "е"))


def is_free_from_game_info(game_info_map: dict) -> bool:
    """True if any store's GameInfo (a dict, or a list of dicts for bundles) marks the game as free."""
    for raw in (game_info_map or {}).values():
        if isinstance(raw, dict) and raw.get("is_free"):
            return True
        if isinstance(raw, list) and any(isinstance(r, dict) and r.get("is_free") for r in raw):
            return True
    return False


def looks_like_giveaway(*texts: str) -> bool:
    """True when any text reads like a free-game giveaway."""
    return any(t and _GIVEAWAY_RE.search(t) for t in texts)


def event_kind(is_free: bool, *texts: str) -> str:
    """Estate event kind — posts are grouped only within the same kind ('free:pc', 'deal:mobile', ...)."""
    platform = "mobile" if any(t and _MOBILE_RE.search(t) for t in texts) else "pc"
    return f"{'free' if is_free else 'deal'}:{platform}"


# ── Store URLs ────────────────────────────────────────────────────────────

def _path_parts(url: str) -> list[str]:
    try:
        return [p for p in urlparse(str(url)).path.split("/") if p]
    except Exception:
        return []


def store_key(store: str, url: str) -> Optional[str]:
    """Exact store identity for one URL, or None if the URL does not point at a game page."""
    url = str(url)
    parts = _path_parts(url)
    store = store.lower()
    if store == "steam":
        m = re.search(r"/app/(\d+)", url)
        return f"steam:{m.group(1)}" if m else None
    if store in ("epicgames", "egs"):
        if "p" in parts and parts.index("p") + 1 < len(parts):
            slug = parts[parts.index("p") + 1].lower()
            if any(c.isdigit() for c in slug[-6:]):
                slug = _EGS_HASH_SUFFIX.sub("", slug)
            return f"egs:{slug}"
        return None
    if store == "gog":
        if "game" in parts and parts.index("game") + 1 < len(parts):
            return f"gog:{parts[parts.index('game') + 1].lower()}"
        return None
    if store == "itch":
        host = urlparse(url).netloc.lower()
        if host.endswith(".itch.io") and parts:
            return f"itch:{host.split('.')[0]}/{parts[0].lower()}"
        return None
    return None


def name_from_url(store: str, url: str) -> Optional[str]:
    """Human-readable game name from a store URL slug ('Astrea_SixSided_Oracles' → 'Astrea SixSided Oracles')."""
    key = store_key(store, url)
    if not key:
        return None
    if key.startswith("steam:"):
        parts = _path_parts(url)
        idx = parts.index("app") if "app" in parts else -1
        slug = parts[idx + 2] if 0 <= idx and idx + 2 < len(parts) else ""
    else:
        slug = key.split(":", 1)[1].split("/")[-1]
    name = re.sub(r"[-_]+", " ", slug).strip()
    if name.islower():  # EGS/GOG/itch slugs are lowercase: 'the forgotten city' → 'The Forgotten City'
        name = name.title()
    return name or None


# ── Headline names ────────────────────────────────────────────────────────

# Everything that separates game names inside a headline: Cyrillic words, brackets, dashes, commas, quotes
_SEPARATORS = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]+|[—–,;()\[\]{}«»\"“”|/]|\s-\s|%")


def _strip_edges(words: list[str]) -> list[str]:
    while words and compact(words[0]) in _EDGE_WORDS:
        words = words[1:]
    while words and compact(words[-1]) in _EDGE_WORDS:
        words = words[:-1]
    return words


def names_from_title(title: str) -> list[str]:
    """Latin-script game names from a (usually Russian) headline."""
    names = []
    for chunk in _SEPARATORS.split(title or ""):
        chunk = chunk.strip(" :!?.'’-+&")
        if not re.search(r"[A-Za-z]", chunk):
            continue
        words = _strip_edges(chunk.split())
        name = " ".join(words).strip(" :!?.-")
        c = compact(name)
        if len(c) >= MIN_NAME_LEN and c not in _GENERIC_CHUNKS and not c.isdigit():
            names.append(name)
    return names


# ── Games grouping ────────────────────────────────────────────────────────

def _info_for(game_info_map: dict, store: str, index: int, total: int) -> Optional[dict]:
    raw = (game_info_map or {}).get(store)
    if isinstance(raw, list):
        raw = raw[index] if index < len(raw) else None
    elif total != 1:
        raw = None
    return raw if isinstance(raw, dict) and raw else None


def games_from_links(store_links: dict, game_info_map: Optional[dict] = None) -> list[dict]:
    """Group store links into games: [{name, links: {store: url}, info: {store: GameInfo dict}}]."""
    games: list[dict] = []
    for store, urls in (store_links or {}).items():
        urls = urls if isinstance(urls, list) else [urls]
        for i, url in enumerate(urls):
            url = str(url)
            info = _info_for(game_info_map, store, i, len(urls))
            name = (info or {}).get("name") or name_from_url(store, url) or ""
            game = {"name": name, "links": {store: url}, "info": {store: info} if info else {}}
            merge_games(games, [game])
    return games


def apply_title_names(games: list[dict], title: str) -> list[dict]:
    """Replace slug-derived names with the properly spelled headline name ('Astrea SixSided Oracles' →
    'Astrea: Six-Sided Oracles') when they are the same game. GameInfo names are kept."""
    by_compact = {compact(n): n for n in names_from_title(title)}
    for game in games:
        if any(i and i.get("name") for i in game.get("info", {}).values()):
            continue
        better = by_compact.get(compact(game.get("name", "")))
        if better:
            game["name"] = better
    return games


def game_keys(game: dict) -> set[str]:
    keys = {k for s, u in game.get("links", {}).items() if (k := store_key(s, u))}
    names = [game.get("name", "")] + [i.get("name", "") for i in game.get("info", {}).values() if i]
    names += [name_from_url(s, u) or "" for s, u in game.get("links", {}).items()]
    keys |= {f"name:{c}" for n in names if len(c := compact(n)) >= MIN_NAME_LEN}
    return keys


def merge_games(existing: list[dict], new: Iterable[dict]) -> list[dict]:
    """Merge games in place: same store key or same compact name → one game."""
    for game in new:
        keys = game_keys(game)
        target = next((g for g in existing if game_keys(g) & keys), None)
        if target is None:
            existing.append({"name": game.get("name", ""), "links": dict(game.get("links", {})),
                             "info": dict(game.get("info", {}))})
            continue
        for store, url in game.get("links", {}).items():
            target["links"].setdefault(store, url)
        for store, info in game.get("info", {}).items():
            if info:
                target["info"].setdefault(store, info)
        # Prefer a real (GameInfo) name over a slug-derived one
        info_name = next((i.get("name") for i in target["info"].values() if i and i.get("name")), None)
        if info_name:
            target["name"] = info_name
        elif not target["name"]:
            target["name"] = game.get("name", "")
    return existing


def post_identity(post) -> dict:
    """What identifies the game event of a parsed Post: {games, is_free, kind, keys}."""
    meta = post.metadata
    games = games_from_links(meta.store_links or {}, meta.game_info or {}) if meta else []
    apply_title_names(games, post.title)
    is_free = is_free_from_game_info((meta.game_info or {}) if meta else {}) or looks_like_giveaway(post.title)
    return {
        "games": games,
        "is_free": is_free,
        "kind": event_kind(is_free, post.title),
        "keys": estate_keys(post.title, games),
    }


def estate_from_post(post) -> dict:
    """A single-post estate dict, e.g. to preview how a post would be formatted."""
    identity = post_identity(post)
    return {
        "estate_id": f"preview-{post.id}",
        "title": post.title,
        "kind": identity["kind"],
        "is_free": identity["is_free"],
        "description": post.content or "",
        "images": list((post.metadata.images or []) if post.metadata else []),
        "tags": list((post.metadata.tags or []) if post.metadata else []),
        "games": identity["games"],
        "posts": [{"post_id": post.id, "source": post.source or "", "post_link": str(post.link), "title": post.title}],
    }


def estate_keys(title: str, games: list[dict]) -> set[str]:
    """All identity keys of an estate: store keys + name keys of its games + names in its headline."""
    keys: set[str] = set()
    for g in games:
        keys |= game_keys(g)
    keys |= {f"name:{compact(n)}" for n in names_from_title(title)}
    return keys
