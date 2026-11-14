"""喜马拉雅：订阅专辑(config.albums) + 声音直链解析。
Cookie 需要网页版登录 cookie（含 1_x_x 设备token 才能取VIP/付费内容）。
"""
import logging
import re

import httpx

from . import Item, Source, StreamSpec, SourceError, register

log = logging.getLogger("aggplay.xmly")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _cookie(cfg: dict) -> str:
    return (cfg["sources"]["ximalaya"].get("cookie") or "").strip()


def _headers(cfg: dict) -> dict:
    return {"User-Agent": UA, "Referer": "https://www.ximalaya.com/",
            "Cookie": _cookie(cfg)}


@register
class XimalayaSource(Source):
    name = "ximalaya"

    def fetch(self, cfg: dict) -> list[Item]:
        albums = cfg["sources"]["ximalaya"].get("albums") or []
        if not albums:
            raise SourceError("未配置喜马拉雅专辑ID（管理页里添加专辑链接即可）")
        items = []
        for album in albums:
            items += self.album_tracks(str(album))
        return items

    def album_tracks(self, album_id: str) -> list[Item]:
        album_id = re.sub(r"\D", "", str(album_id)) or str(album_id)
        items, page = [], 1
        while page <= 50:
            r = httpx.get(
                "https://www.ximalaya.com/revision/album/v1/getTracksList",
                params={"albumId": album_id, "pageNum": page, "pageSize": 30},
                headers={"User-Agent": UA}, timeout=15)
            data = (r.json().get("data") or {})
            tracks = data.get("tracks") or []
            if not tracks:
                break
            for t in tracks:
                items.append(Item(source=self.name, ref=str(t["trackId"]),
                                  title=t.get("title", ""), sub=f"第{t.get('index', '')}集",
                                  kind="track"))
            if len(tracks) < 30:
                break
            page += 1
        if not items:
            raise SourceError(f"专辑 {album_id} 没拉到声音列表")
        return items

    def resolve(self, cfg: dict, item: Item) -> StreamSpec:
        r = httpx.get(
            "https://mobile.ximalaya.com/mobile-playpage/track/v3/baseInfo",
            params={"trackId": item.ref, "device": "web", "caller": "web"},
            headers=_headers(cfg), timeout=15)
        data = r.json().get("trackInfo") or {}
        # 依次尝试低码率aac → 高码率aac → m4a
        for key in ("playPathAacv164", "playPathAacv224", "playPathAacM4a",
                    "playUrlAacv164", "playUrl32"):
            url = data.get(key)
            if url:
                return StreamSpec(url=url, headers={"User-Agent": UA})
        raise SourceError(f"声音 {item.ref} 取不到直链（VIP内容需在配置里填登录cookie）: "
                          f"{str(data)[:120]}")
