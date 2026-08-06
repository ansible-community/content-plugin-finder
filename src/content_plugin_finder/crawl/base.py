from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable

from content_plugin_finder.crawl.context import CrawlContext
from content_plugin_finder.models import Finding, PluginKind


class Crawler(ABC):
    """One plugin-family crawler.

    Crawlers must not call each other. Shared prep lives in CrawlContext.
    """

    name: str
    kinds: frozenset[PluginKind]

    def prepare(self, ctx: CrawlContext) -> None:
        """Optional per-directory setup after context is built."""

    @abstractmethod
    def crawl(self, ctx: CrawlContext) -> Iterable[Finding]:
        raise NotImplementedError
