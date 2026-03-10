#!/opt/bin/python3.14-320l
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

import certifi
from guessit import guessit

API_BASE = "https://api.themoviedb.org/3"

VIDEO_EXTS = {
    ".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".ts", ".mpg", ".mpeg", ".iso",
    ".vob", ".m2ts", ".mts"
}

SKIP_DIR_NAMES = {"VIDEO_TS", "BDMV", "CERTIFICATE", ".actors"}
SKIP_DIR_SUFFIXES = (".trickplay",)

TOKEN = os.environ.get("TMDB_BEARER_TOKEN", "").strip()
DEFAULT_DELAY = float(os.environ.get("TMDB_DELAY", "10"))

HTTP_CTX = ssl.create_default_context(cafile=certifi.where())


def log(msg: str) -> None:
    print(msg, flush=True)


def api_get(path: str, params: dict | None = None) -> dict:
    if not TOKEN:
        raise RuntimeError("TMDB_BEARER_TOKEN não definido no ambiente")

    url = API_BASE + path
    if params:
        q = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{q}"

    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/json",
            "User-Agent": "dns320l-tmdb-imdb/2.0",
        },
    )

    with urllib.request.urlopen(req, timeout=30, context=HTTP_CTX) as resp:
        data = resp.read().decode("utf-8")
        return json.loads(data)


def has_video_here(path: str) -> bool:
    try:
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if os.path.isfile(full):
                ext = os.path.splitext(name)[1].lower()
                if ext in VIDEO_EXTS:
                    return True
    except OSError:
        return False
    return False


def has_video_recursive(path: str) -> bool:
    for root, dirs, files in os.walk(path):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIR_NAMES and not d.endswith(SKIP_DIR_SUFFIXES)
        ]
        for name in files:
            if os.path.splitext(name)[1].lower() in VIDEO_EXTS:
                return True
    return False


def fallback_clean_name(name: str) -> tuple[str, str | None]:
    original = name
    year_match = re.search(r"(19\d{2}|20\d{2})", name)
    year = year_match.group(1) if year_match else None
    s = name

    patterns = [
        r"\bS\d{1,2}E\d{1,2}-E?\d{1,2}\b",
        r"\bS\d{1,2}E\d{1,2}-\d{1,2}\b",
        r"\bS\d{1,2}E\d{1,2}\b",
        r"\bS\d{1,2}-S\d{1,2}\b",
        r"\bS\d{1,2}\b",
        r"\bSeason\s*\d+\s*-\s*\d+\b",
        r"\bSeason\s*\d+\b",
        r"\bTemporada\s*\d+\s*-\s*\d+\b",
        r"\bTemporada\s*\d+\b",
        r"\bWEB[- .]?DL\b",
        r"\bWEBRip\b",
        r"\bBluRay\b",
        r"\bBRRip\b",
        r"\bDVDRip\b",
        r"\bHDTV\b",
        r"\bREMUX\b",
        r"\b1080p\b",
        r"\b2160p\b",
        r"\b720p\b",
        r"\b576p\b",
        r"\b480p\b",
        r"\bx26[45]\b",
        r"\bH\.?26[45]\b",
        r"\bHEVC\b",
        r"\bAVC\b",
        r"\bDUAL\b",
        r"\bDUALAUDIO\b",
        r"\bMULTI\b",
        r"\bDDP?5\.?1\b",
        r"\bAAC(?:2\.0)?\b",
        r"\bAC3\b",
        r"\bAtmos\b",
        r"\bHDR\b",
        r"\bDV\b",
        r"\bNF\b",
        r"\bAMZN\b",
        r"\bHMAX\b",
        r"\bDSNP\b",
        r"\bMAX\b",
        r"\bEZTVx?\.?to\b",
        r"\bMONOLITH\b",
        r"\bPiA\b",
        r"\bWEB\b",
        r"\bDL\b",
        r"\bExtras?\b",
        r"\b\d+\.\d+\b",
        r"\b\d+bit\b",
    ]

    for p in patterns:
        s = re.sub(p, " ", s, flags=re.I)

    s = re.sub(r"\[[^\]]+\]", " ", s)
    s = re.sub(r"\([^\)]*\)", " ", s)
    s = re.sub(r"(19\d{2}|20\d{2})", " ", s)
    s = s.replace(".", " ").replace("_", " ").replace("-", " ").replace("+", " ")
    s = re.sub(r"\s+", " ", s).strip()

    if not s:
        s = original.strip()

    return s, year


def extract_title_year(name: str) -> tuple[str, str | None]:
    try:
        info = guessit(name)
    except Exception:
        info = {}

    title = info.get("title")
    year = info.get("year")

    if isinstance(title, list):
        title = " ".join(str(x) for x in title if x)

    if title:
        title = str(title).strip()
    if year:
        year = str(year)

    if title:
        return title, year

    return fallback_clean_name(name)


def score_candidate(query_title: str, query_year: str | None, item: dict, media_type: str) -> float:
    if media_type == "movie":
        title = (item.get("title") or item.get("original_title") or "").strip()
        date = item.get("release_date") or ""
    else:
        title = (item.get("name") or item.get("original_name") or "").strip()
        date = item.get("first_air_date") or ""

    ratio = SequenceMatcher(None, query_title.lower(), title.lower()).ratio()
    score = ratio * 100.0

    popularity = float(item.get("popularity") or 0.0)
    score += min(popularity / 10.0, 10.0)

    item_year = date[:4] if len(date) >= 4 else None
    if query_year and item_year:
        if query_year == item_year:
            score += 15.0
        else:
            try:
                diff = abs(int(query_year) - int(item_year))
                score += max(0.0, 8.0 - diff * 2.0)
            except ValueError:
                pass

    return score


def best_search_result(title: str, year: str | None, media_type: str) -> dict | None:
    if media_type == "movie":
        path = "/search/movie"
        params = {"query": title, "include_adult": "false"}
        if year:
            params["year"] = year
    else:
        path = "/search/tv"
        params = {"query": title, "include_adult": "false"}
        if year:
            params["first_air_date_year"] = year

    data = api_get(path, params)
    results = data.get("results") or []
    if not results:
        return None

    ranked = sorted(
        results,
        key=lambda x: score_candidate(title, year, x, media_type),
        reverse=True,
    )
    return ranked[0]


def get_movie_imdb_id(movie_id: int) -> str | None:
    data = api_get(f"/movie/{movie_id}")
    imdb_id = data.get("imdb_id")
    return imdb_id or None


def get_tv_imdb_id(tv_id: int) -> str | None:
    data = api_get(f"/tv/{tv_id}/external_ids")
    imdb_id = data.get("imdb_id")
    return imdb_id or None


def write_id_file(folder: str, filename: str, imdb_id: str) -> None:
    out = os.path.join(folder, filename)
    with open(out, "w", encoding="utf-8") as f:
        f.write(imdb_id.strip() + "\n")
    log(f"OK   {out} -> {imdb_id}")


def process_movie_dir(folder: str, delay: float) -> None:
    target = os.path.join(folder, "movie.imdb")
    if os.path.exists(target):
        return
    if not has_video_here(folder):
        return

    base = os.path.basename(folder.rstrip("/"))
    title, year = extract_title_year(base)
    if not title:
        return

    log(f"MOVIE busca: {folder} :: {title} :: year={year}")
    result = best_search_result(title, year, "movie")
    time.sleep(delay)

    if not result:
        log(f"FAIL movie sem match: {folder}")
        return

    movie_id = result.get("id")
    if not movie_id:
        log(f"FAIL movie sem id TMDb: {folder}")
        return

    imdb_id = get_movie_imdb_id(int(movie_id))
    time.sleep(delay)

    if not imdb_id:
        log(f"FAIL movie sem imdb_id: {folder} :: tmdb={movie_id}")
        return

    write_id_file(folder, "movie.imdb", imdb_id)


def process_series_dir(folder: str, delay: float) -> None:
    target = os.path.join(folder, "series.imdb")
    if os.path.exists(target):
        return
    if not has_video_recursive(folder):
        return

    base = os.path.basename(folder.rstrip("/"))
    title, year = extract_title_year(base)
    if not title:
        return

    log(f"SERIE busca: {folder} :: {title} :: year={year}")
    result = best_search_result(title, year, "tv")
    time.sleep(delay)

    if not result:
        log(f"FAIL serie sem match: {folder}")
        return

    tv_id = result.get("id")
    if not tv_id:
        log(f"FAIL serie sem id TMDb: {folder}")
        return

    imdb_id = get_tv_imdb_id(int(tv_id))
    time.sleep(delay)

    if not imdb_id:
        log(f"FAIL serie sem imdb_id: {folder} :: tmdb={tv_id}")
        return

    write_id_file(folder, "series.imdb", imdb_id)


def walk_movies(root: str, delay: float) -> None:
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIR_NAMES and not d.endswith(SKIP_DIR_SUFFIXES)
        ]
        process_movie_dir(current, delay)


def walk_series(root: str, delay: float) -> None:
    try:
        entries = sorted(os.listdir(root))
    except OSError as e:
        raise RuntimeError(f"não consegui listar {root}: {e}")

    for name in entries:
        full = os.path.join(root, name)
        if not os.path.isdir(full):
            continue
        if name in SKIP_DIR_NAMES or name.endswith(SKIP_DIR_SUFFIXES):
            continue
        process_series_dir(full, delay)


def main() -> int:
    if len(sys.argv) < 3:
        log("uso:")
        log("  tmdb_make_imdb.py movies /caminho/Filmes [delay_segundos]")
        log("  tmdb_make_imdb.py series /caminho/Series [delay_segundos]")
        return 1

    mode = sys.argv[1].strip().lower()
    root = sys.argv[2].strip()
    delay = float(sys.argv[3]) if len(sys.argv) >= 4 else DEFAULT_DELAY

    if mode not in {"movies", "series"}:
        log("modo deve ser 'movies' ou 'series'")
        return 1

    if not os.path.isdir(root):
        log(f"caminho não existe ou não é diretório: {root}")
        return 1

    if mode == "movies":
        walk_movies(root, delay)
    else:
        walk_series(root, delay)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())