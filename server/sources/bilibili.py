"""B站：稍后再看列表 + 视频音频流(m4s)解析。
接口文档参考 SocialSisterYi/bilibili-API-collect。Cookie 需要 SESSDATA（移出稍后再看还需 bili_jct）。
"""
import hashlib
import logging
import re
import time
import urllib.parse

import httpx

from . import Item, Source, StreamSpec, SourceError, register

log = logging.getLogger("aggplay.bili")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
API = "https://api.bilibili.com"

# WBI 混淆表（bilibili-API-collect 提供）
MIXIN_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
             27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
             37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
             22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]


def _cookies(cfg: dict) -> str:
    return (cfg["sources"]["bilibili"].get("cookie") or "").strip()


def _get(url: str, cfg: dict, params: dict | None = None, wbi: bool = False) -> dict:
    headers = {"User-Agent": UA, "Referer": "https://www.bilibili.com/",
               "Cookie": _cookies(cfg)}
    if wbi:
        params = dict(params or {})
        params = _wbi_signed(params, cfg)
    r = httpx.get(url, params=params, headers=headers, timeout=15)
    data = r.json()
    if data.get("code") != 0:
        raise SourceError(f"B站接口错误: {data.get('code')} {data.get('message')}")
    return data.get("data") or {}


def _wbi_keys(cfg: dict) -> tuple[str, str] | None:
    try:
        r = httpx.get(f"{API}/x/web-interface/nav",
                      headers={"User-Agent": UA, "Cookie": _cookies(cfg)}, timeout=10)
        w = r.json().get("data", {}).get("wbi_img", {})
        img = (w.get("img_url") or "").split("/")[-1].split(".")[0]
        sub = (w.get("sub_url") or "").split("/")[-1].split(".")[0]
        if img and sub:
            return img, sub
    except Exception as e:
        log.debug("获取wbi_keys失败: %s", e)
    return None


def _wbi_signed(params: dict, cfg: dict) -> dict:
    keys = _wbi_keys(cfg)
    if not keys:
        return params
    mixin = (keys[0] + keys[1])[:64]
    secret = "".join(mixin[i] for i in MIXIN_TAB)[:32]
    params = dict(params)
    params["wts"] = int(time.time())
    q = urllib.parse.urlencode(sorted(params.items()))
    params["w_rid"] = hashlib.md5((q + secret).encode()).hexdigest()
    return params


@register
class BilibiliSource(Source):
    name = "bilibili"

    def fetch(self, cfg: dict) -> list[Item]:
        if not _cookies(cfg):
            raise SourceError("未配置B站Cookie(SESSDATA)")
        data = _get(f"{API}/x/v2/history/toview", cfg)
        items = []
        for v in data.get("list", []):
            items.append(Item(
                source=self.name, ref=v.get("bvid") or f"av{v.get('aid')}",
                title=re.sub(r"<[^>]+>", "", v.get("title", "")),
                sub=v.get("owner", {}).get("name", ""), kind="video",
            ))
        return items

    def resolve(self, cfg: dict, item: Item) -> StreamSpec:
        bvid = self._to_bvid(item.ref, cfg)
        cid = self._cid(bvid, cfg)
        data = _get(f"{API}/x/player/playurl", cfg,
                    params={"bvid": bvid, "cid": cid, "fnval": 16, "qn": 64}, wbi=True)
        audio = (data.get("dash") or {}).get("audio") or []
        if not audio:  # 老视频无DASH，回退FLV/MP4整体文件
            durl = data.get("durl") or [{}]
            if durl and durl[0].get("url"):
                return StreamSpec(url=durl[0]["url"], headers=self._hdr())
            raise SourceError("该视频取不到音频流")
        audio.sort(key=lambda a: a.get("bandwidth", 0))  # 最省流量的音轨
        url = audio[0].get("baseUrl") or audio[0].get("base_url")
        return StreamSpec(url=url, headers=self._hdr())

    @staticmethod
    def _hdr() -> dict:
        return {"Referer": "https://www.bilibili.com/", "User-Agent": UA}

    def _to_bvid(self, ref: str, cfg: dict) -> str:
        if ref.startswith("http"):  # b23.tv 短链
            r = httpx.get(ref, headers={"User-Agent": UA}, follow_redirects=True, timeout=15)
            m = re.search(r"(BV[0-9A-Za-z]{10})", str(r.url))
            if not m:
                raise SourceError(f"短链解析不到BV号: {ref}")
            return m.group(1)
        if ref.startswith("av"):
            data = _get(f"{API}/x/web-interface/view", cfg, params={"aid": int(ref[2:])})
            return data.get("bvid") or ref
        return ref

    def _cid(self, bvid: str, cfg: dict) -> int:
        data = _get(f"{API}/x/player/pagelist", cfg, params={"bvid": bvid})
        first = data[0] if isinstance(data, list) and data else {}
        cid = first.get("cid")
        if not cid:
            raise SourceError(f"取不到cid: {bvid}")
        return cid


def remove_toview(cfg: dict, ref: str) -> None:
    """播完移出稍后再看（需要 bili_jct）。"""
    cookie = _cookies(cfg)
    if "bili_jct" not in cookie:
        return
    m = re.search(r"bili_jct=([^;]+)", cookie)
    aid = ref[2:] if ref.startswith("av") else self_aid(ref)  # noqa: F821
    httpx.post(
        f"{API}/x/v2/history/toview/del",
        data={"aid": aid, "csrf": m.group(1)},
        headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/",
                 "Cookie": cookie}, timeout=10,
    )


def self_aid(ref: str) -> str:
    """BV号转aid：用 view 接口查询。"""
    r = httpx.get(f"{API}/x/web-interface/view",
                  params={"bvid": ref},
                  headers={"User-Agent": UA}, timeout=10)
    return str(r.json().get("data", {}).get("aid", ""))
