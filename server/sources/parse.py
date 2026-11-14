"""从任意分享文本/剪贴板文本里识别内容并路由到对应源。
App 分享接收器和手动粘贴都走这里。
"""
import re

from . import Item


def parse(text: str) -> Item | None:
    t = (text or "").strip()
    if not t:
        return None
    m = re.search(r"(https?://\S+)", t)
    url = m.group(1) if m else ""

    # --- B站：BV号 / av号 / b23.tv 短链（短链解析放 resolve 时做，这里先记下） ---
    m = re.search(r"(BV[0-9A-Za-z]{10})", t)
    if m:
        return Item("bilibili", m.group(1), title=_title_guess(t), kind="video")
    m = re.search(r"av(\d+)", t, re.I)
    if m:
        return Item("bilibili", "av" + m.group(1), title=_title_guess(t), kind="video")
    if "b23.tv" in url:
        return Item("bilibili", url, title=_title_guess(t), kind="video")

    # --- 网易云：song?id=xxx / y.music.163.com/m/song/xxx ---
    m = re.search(r"song[/?]?id=(\d+)|/song/(\d+)", url)
    if "163.com" in url and m:
        sid = m.group(1) or m.group(2)
        return Item("netease", sid, title=_title_guess(t), kind="song")

    # --- 喜马拉雅：/track/123 或 /album/456 ---
    m = re.search(r"ximalaya\.com/track/(\d+)", url)
    if m:
        return Item("ximalaya", m.group(1), title=_title_guess(t), kind="track")
    m = re.search(r"ximalaya\.com/album/(\d+)", url)
    if m:
        return Item("ximalaya", "album:" + m.group(1), title=_title_guess(t), kind="album")

    # --- 微信公众号文章 / 微信读书 ---
    if "mp.weixin.qq.com" in url:
        return Item("weread", url, title=_title_guess(t), kind="wxarticle")
    if "weread.qq.com" in url:
        return Item("weread", url, title=_title_guess(t), kind="book")

    # --- 直链音频兜底 ---
    if re.search(r"https?://\S+\.(mp3|m4a|aac|flac|wav)(\?\S*)?$", url, re.I):
        return Item("manual", url, title=_title_guess(t) or url, kind="direct")

    # --- 其他链接：尝试当通用网页（weread 源的通用文章转语音） ---
    if url:
        return Item("weread", url, title=_title_guess(t), kind="webarticle")

    return None


def _title_guess(text: str) -> str:
    """分享文本里通常带标题，如「【标题】 链接」，尽量取出来。"""
    m = re.match(r"【(.+?)】", text.strip())
    if m:
        return m.group(1)
    # 链接之外的第一个短句
    parts = re.split(r"https?://\S+", text, maxsplit=1)
    head = parts[0].strip(" \n\r，,。#")
    return head[:60] if head else ""
