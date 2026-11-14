"""内容源适配器基类与注册表。每个源独立实现，坏了单独修。"""
from dataclasses import dataclass, field


@dataclass
class Item:
    source: str
    ref: str                 # 源内唯一标识
    title: str = ""
    sub: str = ""            # 副标题（UP主/歌手/专辑…）
    kind: str = ""           # video/song/track/article/book...


@dataclass
class StreamSpec:
    url: str                 # 音频直链或待代理页面
    headers: dict = field(default_factory=dict)  # 拉流需要的请求头（Referer/UA/Cookie）
    transcode: bool = True   # True=强制 ffmpeg 转 mp3@128k（L05C 不吃 flac/m4s）
    tts_text: str | None = None  # 非空时跳过ffmpeg，直接 edge-tts 合成该文本


class SourceError(Exception):
    pass


class Source:
    name = "base"

    def enabled(self, cfg: dict) -> bool:
        return cfg["sources"].get(self.name, {}).get("enabled", False)

    def fetch(self, cfg: dict) -> list[Item]:
        """拉取该源的收藏/待听列表，返回 Item 列表（按期望播放顺序）。"""
        raise NotImplementedError

    def resolve(self, cfg: dict, item: Item) -> StreamSpec:
        """把 Item 解析成可播放的音频流。"""
        raise NotImplementedError


REGISTRY: dict[str, type[Source]] = {}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls


def get(name: str) -> Source:
    return REGISTRY[name]()


def all_sources() -> dict[str, Source]:
    return {n: c() for n, c in REGISTRY.items()}
