"""微信读书/文章转语音：公众号文章、网页文章抓正文 → edge-tts 流式合成。
书架/电子书章节为实验性（微信读书web端反爬较强），文章类稳定。
"""
import logging
import re

import httpx
from bs4 import BeautifulSoup

from . import Item, Source, StreamSpec, SourceError, register

log = logging.getLogger("aggplay.weread")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _cookie(cfg: dict) -> str:
    return (cfg["sources"]["weread"].get("cookie") or "").strip()


@register
class WereadSource(Source):
    name = "weread"

    def fetch(self, cfg: dict) -> list[Item]:
        s = cfg["sources"]["weread"]
        items = []
        for url in s.get("articles") or []:
            items.append(Item(self.name, url, title=_url_title(url), kind="wxarticle"))
        for book in s.get("books") or []:
            items.append(Item(self.name, str(book), title=f"读书 {book}", kind="book"))
        if not items:
            raise SourceError("未配置微信读书内容（管理页可粘贴文章链接）")
        return items

    def resolve(self, cfg: dict, item: Item) -> StreamSpec:
        if item.kind in ("wxarticle", "webarticle"):
            text = self._article_text(item.ref)
            if len(text) < 30:
                raise SourceError("文章正文抓取失败（可能需要登录或链接失效）")
            return StreamSpec(url=item.ref, tts_text=text)
        if item.kind == "book":
            text = self._book_chapter(cfg, item.ref)
            if len(text) < 30:
                raise SourceError("书籍章节抓取失败（实验性，建议优先用文章链接）")
            return StreamSpec(url=item.ref, tts_text=text)
        raise SourceError(f"未知类型 {item.kind}")

    # ---- 文章 ----
    def _article_text(self, url: str) -> str:
        r = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        node = soup.select_one("#js_content") or soup.select_one("article") or soup.body
        title = (soup.select_one("h1") or soup.select_one("title"))
        title = title.get_text(strip=True) if title else "文章"
        text = re.sub(r"\n{3,}", "\n\n", node.get_text("\n", strip=True))
        return f"{title}。\n{text}"

    # ---- 书籍章节（实验性）----
    def _book_chapter(self, cfg: dict, book_id: str) -> str:
        headers = {"User-Agent": UA, "Cookie": _cookie(cfg),
                   "Referer": "https://weread.qq.com/"}
        if not _cookie(cfg):
            raise SourceError("读书功能需要微信读书cookie(wr_vid+wr_skey)")
        r = httpx.post(
            "https://i.weread.qq.com/book/chapterInfos",
            json={"bookIds": [book_id], "synckeys": 0}, headers=headers, timeout=15)
        data = r.json().get("data") or []
        if not data or not (data[0].get("updated") or data[0].get("chapters")):
            raise SourceError(f"取不到章节列表: {str(r.json())[:120]}")
        chapters = data[0].get("chapters") or []
        chapter = chapters[0]  # v1: 从第一章开始
        return self._chapter_content(cfg, book_id, chapter["chapterUid"])

    def _chapter_content(self, cfg: dict, book_id: str, chapter_uid: int) -> str:
        headers = {"User-Agent": UA, "Cookie": _cookie(cfg),
                   "Referer": "https://weread.qq.com/"}
        r = httpx.get(f"https://i.weread.qq.com/web/book/{book_id}/{chapter_uid}",
                      headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        text = soup.get_text("\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", text)


def _url_title(url: str) -> str:
    try:
        r = httpx.head(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=10)
        ct = r.headers.get("content-type", "")
        if "html" not in ct:
            return url.split("/")[-1][:30]
    except Exception:
        pass
    return url.split("?")[0][-40:]
