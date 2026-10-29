"""قارئ robots.txt بيدعم * و $ زي جوجل.

مكتبة Python الجاهزة (urllib.robotparser) مش بتفهم *، وكارفور مثلًا بيستخدمها
في قواعد زي  Disallow: /*search=*  ، فكتبنا قارئ صغير بنفسنا.

القواعد: أطول قاعدة بتنطبق على الرابط هي اللي بتكسب، ولو اتساووا Allow بيكسب.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class _Group:
    agents: list = field(default_factory=list)
    rules: list = field(default_factory=list)      # (allow: bool, pattern: str)
    crawl_delay: float | None = None


def _matches(pattern: str, path: str) -> bool:
    """قاعدة robots زي جوجل (* = أي حاجة، $ = آخر الرابط) من غير regex: «/*a*a*a…*b» كانت بتاخد ثواني
    (فحص الأمان). بندوّر على كل جزء بعد اللي قبله (أول مكان)، وده كفاية للـ * زي ما الـ regex الكسلان بيعمل."""
    anchored = pattern.endswith("$")
    parts = (pattern[:-1] if anchored else pattern).split("*")
    if not path.startswith(parts[0]):
        return False
    i = len(parts[0])
    for p in parts[1:]:
        j = path.find(p, i)
        if j < 0:
            return False
        i = j + len(p)
    if not anchored:
        return True
    if len(parts) == 1:
        return path == parts[0]
    return path.endswith(parts[-1]) and len(path) - len(parts[-1]) >= len(parts[0])


class Robots:
    def __init__(self, text: str):
        self.groups: list[_Group] = []
        self.sitemaps: list[str] = []
        current: _Group | None = None
        last_was_agent = False
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, value = (p.strip() for p in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = _Group()
                    self.groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if key == "sitemap":
                self.sitemaps.append(value)
            elif current is None:
                continue
            elif key in ("allow", "disallow"):
                if value:  # "Disallow:" فاضية معناها مسموح كله
                    current.rules.append((key == "allow", value))
            elif key == "crawl-delay":
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    pass

    def _group_for(self, user_agent: str) -> _Group | None:
        ua = user_agent.lower()
        best, best_len = None, -1
        for g in self.groups:
            for a in g.agents:
                if a != "*" and a in ua and len(a) > best_len:
                    best, best_len = g, len(a)
        if best:
            return best
        return next((g for g in self.groups if "*" in g.agents), None)

    def allowed(self, user_agent: str, url: str) -> bool:
        group = self._group_for(user_agent)
        if not group:
            return True
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        verdict, best_len = True, -1
        for allow, pattern in group.rules:
            target = path if pattern.startswith("/") else path.lstrip("/")
            if _matches(pattern, target):
                if len(pattern) > best_len or (len(pattern) == best_len and allow):
                    verdict, best_len = allow, len(pattern)
        return verdict

    def crawl_delay(self, user_agent: str) -> float | None:
        group = self._group_for(user_agent)
        return group.crawl_delay if group else None
