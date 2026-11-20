"""教务处公开信息：通知公告、学年校历（无需登录）。"""
import re
from typing import Any
from urllib.parse import urljoin

import requests

from . import config as C
from .parsers import soup

HEADERS = {"User-Agent": C.USER_AGENT}


def _fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=20)
    raw = r.content
    head = raw[:2048].lower()
    enc = "utf-8"
    m = re.search(rb'charset=["\']?([\w-]+)', head)
    if m:
        enc = m.group(1).decode("ascii", "ignore")
    if enc.lower().startswith("gb"):
        enc = "gb18030"
    try:
        return raw.decode(enc)
    except Exception:
        return raw.decode("utf-8", "ignore")


def _date_near(tag, text: str) -> str:
    node = tag
    for _ in range(4):
        if node is None:
            break
        m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", node.get_text(" ", strip=True))
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        node = node.parent
    m = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", text)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return ""


def notices(limit: int = 20) -> list[dict[str, Any]]:
    """通知公告：教务处的学业通知 + 公告通知。"""
    items: list[dict[str, Any]] = []
    seen = set()
    for page, kind in (("index/xytz.htm", "学业通知"), ("index/fftz.htm", "公告通知")):
        try:
            html = _fetch(f"{C.JWC_BASE}/{page}")
        except Exception:
            continue
        doc = soup(html)
        for a in doc.find_all("a", href=True):
            title = a.get_text(" ", strip=True)
            href = a["href"]
            if len(title) < 8 or not re.search(r"(info/\d+/\d+|new-article)", href):
                continue
            url = urljoin(f"{C.JWC_BASE}/{page}", href)
            if url in seen:
                continue
            seen.add(url)
            items.append({
                "title": title,
                "url": url,
                "date": _date_near(a, title),
                "kind": kind,
            })
        if len(items) >= limit:
            break
    items.sort(key=lambda x: x.get("date") or "", reverse=True)
    return items[:limit]


def calendar() -> dict[str, Any]:
    """学年校历列表（教务处发布的各学期校历页）。"""
    out = {"items": [], "term_start_guess": ""}
    try:
        html = _fetch(f"{C.JWC_BASE}/index/xnxl.htm")
    except Exception as exc:
        out["error"] = str(exc)
        return out
    doc = soup(html)
    seen = set()
    for a in doc.find_all("a", href=True):
        href = a["href"]
        if not re.search(r"info/\d+/\d+\.htm", href):
            continue
        title_tag = a.find("h3")
        title = title_tag.get_text(" ", strip=True) if title_tag else a.get_text(" ", strip=True)
        title = re.sub(r"\s+", " ", title).strip()
        if not title or "校历" not in title:
            continue
        url = urljoin(f"{C.JWC_BASE}/index/xnxl.htm", href)
        if url in seen:
            continue
        seen.add(url)
        date = ""
        time_tag = a.find("p", class_="time")
        if time_tag:
            m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", time_tag.get_text(" ", strip=True))
            if m:
                date = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        out["items"].append({"title": title, "url": url, "date": date})
    out["items"] = out["items"][:10]
    return out
