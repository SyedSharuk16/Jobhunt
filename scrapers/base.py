import time
import random
from abc import ABC, abstractmethod


class BaseScraper(ABC):
    name: str = "base"

    def _sleep(self, lo: float = 1.5, hi: float = 3.5) -> None:
        time.sleep(random.uniform(lo, hi))

    @abstractmethod
    def scrape(self, keywords: list[str], location: str, pages: int) -> list[dict]:
        """Return a list of raw job dicts."""
        ...
