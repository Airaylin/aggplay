"""语音意图解析：把用户对音箱说的话解析成播放指令。
匹配不到的返回 None（不抢小爱原生功能）。
"""
import re

_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

SOURCE_ALIAS = [
    ("bilibili", r"B站|哔哩哔哩|bilibili|bili"),
    ("netease", r"网易云?音乐?|网易"),
    ("ximalaya", r"喜马拉雅"),
    ("weread", r"微信读书|微信?书|听书"),
    ("manual", r"手动|投递"),
]


def _cn2int(s: str) -> int | None:
    if s.isdigit():
        return int(s)
    if len(s) == 1 and s in _CN_NUM:
        return _CN_NUM[s]
    if s == "十":
        return 10
    m = re.fullmatch(r"([一二三四五六七八九])?十([一二三四五六七八九])?", s)
    if m:
        tens = _CN_NUM.get(m.group(1), 1) if m.group(1) else 1
        ones = _CN_NUM.get(m.group(2), 0) if m.group(2) else 0
        return tens * 10 + ones
    return None


def parse(text: str) -> dict | None:
    t = re.sub(r"[。！？!?，, ]+", "", (text or "").strip())
    if not t:
        return None

    # --- 播放控制（无"播放"前缀的短口令）---
    if re.fullmatch(r"(停止|停止播放|别放了|别播放|关掉|停止音乐|停止放音)", t):
        return {"action": "stop"}
    if re.fullmatch(r"(暂停|暂停播放|停一下|等一下)", t):
        return {"action": "pause"}
    if re.fullmatch(r"(继续|继续播放|接着放|接着播放)", t):
        return {"action": "resume"}
    if re.fullmatch(r"(下一个|下一首|下一集|换一个|跳过|再换一个)", t):
        return {"action": "next"}
    if re.fullmatch(r"(上一个|上一首|上一集|回退一个)", t):
        return {"action": "prev"}

    # --- 音量 ---
    m = re.search(r"音量(调)?(大一点|大些|加|加到)?([0-9]+)?", t)
    if t.startswith("音量"):
        if "大" in t:
            return {"action": "volume", "value": "+10"}
        if "小" in t:
            return {"action": "volume", "value": "-10"}
        m2 = re.search(r"音量(调到?|设为?)?([0-9]+)", t)
        if m2:
            return {"action": "volume", "value": int(m2.group(2))}

    # --- 列表播报 ---
    if re.search(r"(有什么|有哪些|什么内容|列表|清单|播报清单|我的待听有)", t) and not t.startswith("播放"):
        return {"action": "list"}

    # --- 播放类（需以 播放/放/开始/来点/听 开头的口语）---
    if not re.match(r"(播放|放|开始播放|来点|来首|我要听|听)", t):
        return None

    # 第N个
    m = re.search(r"第([0-9]+|[一两二三四五六七八九十]{1,3})(个|首|条|集)", t)
    if m:
        n = _cn2int(m.group(1))
        if n:
            return {"action": "play", "index": n - 1}

    # 按源过滤
    for source, pattern in SOURCE_ALIAS:
        if re.search(pattern, t, re.I):
            return {"action": "play", "source": source}

    # 全队列
    if re.search(r"(我的待听|待听|稍后再看|收藏|全部|队列|开始|继续)", t):
        return {"action": "play"}

    # 兜底：播放+标题关键词（模糊匹配队列内条目）
    title = re.sub(r"^(播放|放|开始播放|来点|来首|我要听|听)", "", t)
    title = re.sub(r"(第([0-9]+|[一两二三四五六七八九十]{1,3})(个|首|条|集))$", "", title)
    if title:
        return {"action": "play", "query": title}
    return None
