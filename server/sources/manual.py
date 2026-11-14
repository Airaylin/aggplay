"""手动投递：直链音频（.mp3/.m4a等）。列表由 /api/add 动态入队，无固定列表。"""
import logging

from . import Item, Source, StreamSpec, register

log = logging.getLogger("aggplay.manual")


@register
class ManualSource(Source):
    name = "manual"

    def fetch(self, cfg: dict) -> list[Item]:
        return []  # 手动条目只通过 App 分享/粘贴入队，不参与全量刷新

    def resolve(self, cfg: dict, item: Item) -> StreamSpec:
        return StreamSpec(url=item.ref, transcode=True)
