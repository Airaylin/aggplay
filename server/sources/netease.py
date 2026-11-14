"""网易云音乐：我喜欢的音乐/歌单 + 歌曲直链（纯Python实现weapi加密，无需额外容器）。
Cookie 需要 MUSIC_U（网页版或客户端抓包）。VIP歌需要账号本身有会员。
"""
import base64
import json
import logging
import random
import string

import httpx
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

from . import Item, Source, StreamSpec, SourceError, register

log = logging.getLogger("aggplay.netease")

PRESET_KEY = b"0CoJm6QQywKWWdIN"
IV = b"0102030405060708"
RSA_E = "010001"
RSA_N = ("00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7"
         "b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280"
         "104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932"
         "575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b3"
         "ece0462db0a22b8e7")
CHARSET = string.ascii_letters + string.digits
BASE_COOKIE = ("os=pc; osver=Microsoft-Windows-10; appver=9.0.10; "
               "naviversion=1.0.1; hoster=music.163.com")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _aes(text: str, key: bytes) -> str:
    cipher = AES.new(key if isinstance(key, bytes) else key.encode(),
                     AES.MODE_CBC, IV)
    return base64.b64encode(cipher.encrypt(pad(text.encode(), 16))).decode()


def _rsa(secret: str) -> str:
    sec_hex = secret[::-1].encode().hex()  # 逆序后转hex
    r = pow(int(sec_hex, 16), int(RSA_E, 16), int(RSA_N, 16))
    return format(r, "0>256x")


def weapi(path: str, data: dict, cookie: str) -> dict:
    text = json.dumps(data)
    secret_key = "".join(random.choices(CHARSET, k=16))
    params = _aes(_aes(text, PRESET_KEY), secret_key.encode())
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://music.163.com/",
        "User-Agent": UA,
        "Cookie": BASE_COOKIE + ("; " + cookie if cookie else ""),
    }
    r = httpx.post("https://music.163.com/weapi/" + path.lstrip("/"),
                   data={"params": params, "encSecKey": _rsa(secret_key)},
                   headers=headers, timeout=15)
    return r.json()


def _cookie(cfg: dict) -> str:
    return (cfg["sources"]["netease"].get("cookie") or "").strip()


@register
class NeteaseSource(Source):
    name = "netease"

    def fetch(self, cfg: dict) -> list[Item]:
        if "MUSIC_U" not in _cookie(cfg):
            raise SourceError("未配置网易云Cookie(MUSIC_U)")
        acc = weapi("nuser/account/get", {}, _cookie(cfg))
        uid = (acc.get("account") or acc.get("profile") or {}).get("id") or \
              (acc.get("profile") or {}).get("userId")
        if not uid:
            raise SourceError(f"网易云账号信息获取失败: {str(acc)[:120]}")
        playlists = cfg["sources"]["netease"].get("playlists") or []
        if playlists:
            ids, titles = [], {}
            for pl in playlists:
                detail = weapi("playlist/detail", {"id": int(pl), "n": 1000, "s": 8},
                               _cookie(cfg))
                pl = detail.get("playlist") or {}
                ids += [t["id"] for t in (pl.get("trackIds") or [])]
                titles.update({t["id"]: t["name"] for t in (pl.get("tracks") or [])})
            return self._detail_items(ids, titles)
        liked = weapi("song/like/get", {"uid": uid}, _cookie(cfg))
        ids = liked.get("ids") or []
        return self._detail_items(ids, {})

    def _detail_items(self, ids: list, known: dict) -> list[Item]:
        items = []
        for i in range(0, len(ids), 200):
            chunk = ids[i:i + 200]
            detail = weapi("v3/song/detail",
                           {"c": json.dumps([{"id": j} for j in chunk])}, "")
            for s in detail.get("songs") or []:
                artists = "/".join(a["name"] for a in s.get("ar") or [])
                items.append(Item(source=self.name, ref=str(s["id"]),
                                  title=s.get("name", ""), sub=artists, kind="song"))
        return items

    def resolve(self, cfg: dict, item: Item) -> StreamSpec:
        data = weapi("song/enhance/player/url/v1",
                     {"ids": json.dumps([int(item.ref)]),
                      "level": "standard", "encodeType": "aac"},
                     _cookie(cfg))
        url = ((data.get("data") or [{}])[0]).get("url")
        if not url:
            fee = (data.get("data") or [{}])[0]
            raise SourceError(
                f"取不到播放链接（无版权或需VIP）: code={fee.get('code')} fee={fee.get('fee')}")
        return StreamSpec(url=url, headers={"User-Agent": UA})
