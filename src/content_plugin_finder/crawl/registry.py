from __future__ import annotations

from content_plugin_finder.crawl.base import Crawler
from content_plugin_finder.models import PluginKind


class CrawlerRegistry:
    def __init__(self) -> None:
        self._crawlers: dict[str, Crawler] = {}

    def register(self, crawler: Crawler) -> None:
        if crawler.name in self._crawlers:
            raise ValueError(f"crawler already registered: {crawler.name}")
        self._crawlers[crawler.name] = crawler

    def get(self, name: str) -> Crawler:
        return self._crawlers[name]

    def all(self) -> list[Crawler]:
        return [self._crawlers[name] for name in sorted(self._crawlers)]

    def for_kinds(
        self, kinds: set[PluginKind] | frozenset[PluginKind]
    ) -> list[Crawler]:
        selected: list[Crawler] = []
        for crawler in self.all():
            if crawler.kinds & kinds:
                selected.append(crawler)
        return selected

    def list_info(self) -> list[dict[str, str]]:
        return [
            {
                "name": c.name,
                "kinds": ",".join(sorted(k.value for k in c.kinds)),
            }
            for c in self.all()
        ]


def _build_default_registry() -> CrawlerRegistry:
    from content_plugin_finder.crawl.filters import FilterCrawler
    from content_plugin_finder.crawl.lookups import LookupCrawler
    from content_plugin_finder.crawl.modules import ModuleCrawler
    from content_plugin_finder.crawl.roles import RoleCrawler

    registry = CrawlerRegistry()
    registry.register(ModuleCrawler())
    registry.register(FilterCrawler())
    registry.register(LookupCrawler())
    registry.register(RoleCrawler())
    return registry


_DEFAULT: CrawlerRegistry | None = None


def default_registry() -> CrawlerRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = _build_default_registry()
    return _DEFAULT
