"""Free (key-less) translation backends with caching and fallback."""

from __future__ import annotations

import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, Sequence

import requests

from .cache import TranslationCache

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;:])\s+")
_TAG = re.compile(r"</?g\b[^>]*>")


class TranslationError(RuntimeError):
    pass


def _split_chunks(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for piece in _SENTENCE_SPLIT.split(text):
        while len(piece) > limit:
            cut = piece.rfind(" ", 0, limit) or limit
            chunks.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        if not current:
            current = piece
        elif len(current) + len(piece) + 1 <= limit:
            current = f"{current} {piece}"
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


class Provider:
    name = "provider"
    char_limit = 1000

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    def translate_chunk(self, text: str, source: str, target: str) -> str:
        raise NotImplementedError

    def translate(self, text: str, source: str, target: str) -> str:
        parts = [
            self.translate_chunk(chunk, source, target)
            for chunk in _split_chunks(text, self.char_limit)
        ]
        return " ".join(p.strip() for p in parts if p.strip())


class GoogleProvider(Provider):
    """Unofficial `translate_a/single` endpoint used by the Google Translate web widget."""

    name = "google"
    char_limit = 1800
    URL = "https://translate.googleapis.com/translate_a/single"

    def translate_chunk(self, text: str, source: str, target: str) -> str:
        params = {"client": "gtx", "sl": source, "tl": target, "dt": "t"}
        response = self.session.post(self.URL, params=params, data={"q": text}, timeout=20)
        if response.status_code != 200:
            raise TranslationError(f"google HTTP {response.status_code}")
        payload = response.json()
        if not payload or not payload[0]:
            raise TranslationError("google: empty response")
        return "".join(seg[0] for seg in payload[0] if seg and seg[0])


class BingProvider(Provider):
    """Unofficial bing.com/translator endpoint (requires a scraped page token)."""

    name = "bing"
    char_limit = 900
    PAGE = "https://www.bing.com/translator"
    LANGS = {"zh-CN": "zh-Hans", "zh": "zh-Hans", "zh-TW": "zh-Hant"}

    def __init__(self) -> None:
        super().__init__()
        self.session.headers.update({"Referer": self.PAGE, "Origin": "https://www.bing.com"})
        self._auth: tuple[str, str, str, str] | None = None
        self._auth_time = 0.0
        self._lock = threading.Lock()

    def _authenticate(self) -> tuple[str, str, str, str]:
        with self._lock:
            if self._auth and time.time() - self._auth_time < 480:
                return self._auth
            page = self.session.get(self.PAGE, timeout=20).text
            ig = re.search(r'IG:"([^"]+)"', page)
            iid = re.search(r'data-iid="([^"]+)"', page)
            helper = re.search(r"params_AbusePreventionHelper\s*=\s*(\[.*?\])", page)
            if not (ig and iid and helper):
                raise TranslationError("bing: could not read page token")
            key, token, _ = json.loads(helper.group(1))
            self._auth = (ig.group(1), iid.group(1), str(key), token)
            self._auth_time = time.time()
            return self._auth

    def translate_chunk(self, text: str, source: str, target: str) -> str:
        ig, iid, key, token = self._authenticate()
        response = self.session.post(
            "https://www.bing.com/ttranslatev3",
            params={"isVertical": "1", "IG": ig, "IID": iid},
            data={
                "fromLang": "auto-detect" if source == "auto" else source,
                "to": self.LANGS.get(target, target),
                "text": text,
                "token": token,
                "key": key,
            },
            timeout=20,
        )
        if response.status_code != 200:
            self._auth = None
            raise TranslationError(f"bing HTTP {response.status_code}")
        payload = response.json()
        if isinstance(payload, dict):
            self._auth = None
            raise TranslationError(f"bing: {payload.get('statusCode', payload)}")
        return payload[0]["translations"][0]["text"]


class MyMemoryProvider(Provider):
    """api.mymemory.translated.net — key-less, ~500 byte queries, daily quota."""

    name = "mymemory"
    char_limit = 480
    URL = "https://api.mymemory.translated.net/get"

    def translate_chunk(self, text: str, source: str, target: str) -> str:
        src = "en" if source == "auto" else source
        response = self.session.get(
            self.URL, params={"q": text, "langpair": f"{src}|{target}"}, timeout=20
        )
        if response.status_code != 200:
            raise TranslationError(f"mymemory HTTP {response.status_code}")
        payload = response.json()
        if payload.get("responseStatus") not in (200, "200"):
            raise TranslationError(f"mymemory: {payload.get('responseDetails')}")
        text = payload["responseData"]["translatedText"]
        return html.unescape(_TAG.sub("", text))


PROVIDERS: dict[str, type[Provider]] = {
    "google": GoogleProvider,
    "bing": BingProvider,
    "mymemory": MyMemoryProvider,
}


class Translator:
    """Translates many paragraphs with a thread pool, cache and provider fallback."""

    def __init__(
        self,
        provider: str = "google",
        target: str = "zh-CN",
        source: str = "en",
        workers: int = 4,
        use_cache: bool = True,
        fallback: bool = True,
    ):
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider: {provider}")
        order = [provider] + [p for p in PROVIDERS if fallback and p != provider]
        self._chain = [PROVIDERS[name]() for name in order]
        self.target = target
        self.source = source
        self.workers = max(1, workers)
        self.cache = TranslationCache() if use_cache else None
        self._failed: set[str] = set()
        self._lock = threading.Lock()

    def translate_text(self, text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        if self.cache:
            hit = self.cache.get("any", self.target, text)
            if hit is not None:
                return hit
        errors = []
        for provider in self._chain:
            with self._lock:
                if provider.name in self._failed:
                    continue
            for attempt in range(2):
                try:
                    result = provider.translate(text, self.source, self.target)
                    if result.strip():
                        if self.cache:
                            self.cache.put("any", self.target, text, result)
                        return result
                except Exception as exc:  # noqa: BLE001 - report and fall through
                    errors.append(f"{provider.name}: {exc}")
                    time.sleep(0.8 * (attempt + 1))
            with self._lock:
                self._failed.add(provider.name)
        raise TranslationError("; ".join(errors) or "all providers failed")

    def translate_many(
        self,
        texts: Sequence[str],
        on_result: Callable[[int, str, str | None], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> list[str]:
        results: list[str] = [""] * len(texts)

        def work(item: tuple[int, str]) -> None:
            i, text = item
            if should_stop and should_stop():
                return
            try:
                results[i] = self.translate_text(text)
                error = None
            except Exception as exc:  # noqa: BLE001 - surfaced to the UI
                results[i] = ""
                error = str(exc)
            if on_result:
                on_result(i, results[i], error)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            list(pool.map(work, enumerate(texts)))
        return results


def available_providers() -> Iterable[str]:
    return PROVIDERS.keys()
