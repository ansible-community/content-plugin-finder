"""Pluggable crawler subsystem for discovering Ansible plugin usage."""

from content_plugin_finder.crawl.registry import CrawlerRegistry, default_registry

__all__ = ["CrawlerRegistry", "default_registry"]
