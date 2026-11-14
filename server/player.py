"""播放引擎：选定条目、报幕、让音箱拉流、监控播放状态、自动连播。"""
import asyncio
import logging
import time
from dataclasses import fields as dc_fields

from .config import stream_token
from .sources import Item, all_sources
from .sources.bilibili import BilibiliSource  # noqa: F401  (注册)
from .sources.netease import NeteaseSource  # noqa: F401
from .sources.ximalaya import XimalayaSource  # noqa: F401
from .sources.weread import WereadSource  # noqa: F401
from .sources.manual import ManualSource  # noqa: F401

log = logging.getLogger("aggplay.player")

SOURCE_NAMES = {"bilibili": "B站", "netease": "网易云", "ximalaya": "喜马拉雅",
                "weread": "微信读书", "manual": "手动投递"}


class Player:
    def __init__(self, cfg: dict, store, speaker):
        self.cfg = cfg
        self.store = store
        self.speaker = speaker
        self.current: dict | None = None
        self.base_url = ""            # 由 main 启动时填充（音箱可达的服务器地址）
        self._was_playing = False
        self._suppress_until = 0.0    # 报幕/起播窗口内不判定"播完"
        self._advance_lock = asyncio.Lock()
        self._spec_cache: dict[int, object] = {}   # item_id -> StreamSpec
        self._tts_texts: dict[int, str] = {}       # item_id -> 待合成文本(weread)
        self._fail_counts: dict[str, int] = {}

    # ---------- 基础 ----------
    def stream_url(self, item_id: int) -> str:
        return f"{self.base_url.rstrip('/')}/stream/{stream_token(self.cfg)}/{item_id}"

    async def start(self) -> None:
        asyncio.create_task(self._monitor_loop())

    def _row_to_item(self, row: dict) -> Item:
        names = {f.name for f in dc_fields(Item)}
        return Item(**{k: row[k] for k in names if k in row})

    def _resolve(self, row: dict):
        src = all_sources()[row["source"]]
        return src.resolve(self.cfg, self._row_to_item(row))

    # ---------- 选条与开播 ----------
    def _pick(self, index=None, source=None, item_id=None, query=None) -> dict | None:
        items = self.store.list(source)
        if item_id is not None:
            row = self.store.get(item_id)
            if row:
                return row
        if query:
            q = query.lower()
            for it in items:
                if q in (it["title"] or "").lower():
                    return it
            return None
        if index is not None:
            return items[index] if 0 <= index < len(items) else None
        return items[0] if items else None

    async def play(self, index=None, source=None, item_id=None, query=None) -> str:
        """对外入口：返回给 TTS 说的话。"""
        item = self._pick(index=index, source=source, item_id=item_id, query=query)
        if not item:
            if query:
                return f"没找到包含{query[:10]}的内容"
            return "待听队列是空的，去管理页添加内容吧"
        items = self.store.list(source)
        try:
            pos = [i["id"] for i in items].index(item["id"]) + 1
        except ValueError:
            pos = 1
        total = len(items)
        await self._start_item(item, announce_pos=(pos, total))
        return f"开始播放第{pos}条，共{total}条"

    async def _start_item(self, item: dict, announce_pos=None) -> None:
        if self.current and self.current["id"] != item["id"]:
            self._finish(self.current, "played")
        self.current = item
        self._was_playing = False
        self.store.set_status(item["id"], "playing")
        try:
            spec = await asyncio.wait_for(asyncio.to_thread(self._resolve, item), 40)
        except Exception as e:
            log.warning("解析失败 %s/%s: %s", item["source"], item["ref"], e)
            ref = f"{item['source']}:{item['ref']}"
            self._fail_counts[ref] = self._fail_counts.get(ref, 0) + 1
            if self._fail_counts[ref] >= 3:
                self._finish(item, "failed")
            await self._advance(f"这条内容解析失败，{SOURCE_NAMES.get(item['source'], '')}已跳过")
            return
        self._spec_cache[item["id"]] = spec
        if announce_pos and self.cfg.get("announce", True):
            pos, total = announce_pos
            title = (item["title"] or "")[:22]
            try:
                await self.speaker.tts(f"第{pos}条，共{total}条。{title}")
            except Exception as e:
                log.warning("报幕失败: %s", e)
        self._suppress_until = time.time() + 8  # 报幕+起播窗口
        await self.speaker.play_url(self.stream_url(item["id"]))
        log.info("已推送播放: [%s] %s", item["source"], item["title"])

    def _finish(self, item: dict, status: str) -> None:
        self.store.set_status(item["id"], status)
        self._spec_cache.pop(item["id"], None)
        self._tts_texts.pop(item["id"], None)
        if self.current and self.current["id"] == item["id"]:
            self.current = None

    async def _advance(self, say: str | None = None) -> None:
        async with self._advance_lock:
            if self.current:
                self._finish(self.current, "played")
                self._post_play(self.current)
            nxt = self.store.list()
            nxt = nxt[0] if nxt else None
            if nxt:
                await self._start_item(nxt, announce_pos=None)
            else:
                self.current = None
                if say:
                    try:
                        await self.speaker.tts(say)
                    except Exception:
                        pass
                else:
                    try:
                        await self.speaker.tts("待听队列播完了")
                    except Exception:
                        pass

    def _post_play(self, item: dict) -> None:
        """播完回写：B站可选移出稍后再看。"""
        if item["source"] == "bilibili" and self.cfg.get("bili_remove_after_play"):
            def _do():
                try:
                    from .sources.bilibili import remove_toview
                    remove_toview(self.cfg, item["ref"])
                except Exception as e:
                    log.warning("移出稍后再看失败: %s", e)
            import threading
            threading.Thread(target=_do, daemon=True).start()

    # ---------- 控制 ----------
    async def next(self) -> None:
        await self._advance()

    async def prev(self) -> None:
        row = self.store.db.execute(
            "SELECT * FROM items WHERE status='played' ORDER BY played_at DESC LIMIT 1"
        ).fetchone()
        if row:
            row = dict(row)
            self.store.set_status(row["id"], "pending")
            await self._start_item(row)
        else:
            await self.speaker.tts("没有上一条了")

    async def stop(self) -> None:
        self._was_playing = False
        cur, self.current = self.current, None
        if cur:
            self._finish(cur, "played")
        await self.speaker.stop()

    async def pause(self) -> None:
        await self.speaker.pause()

    async def resume(self) -> None:
        await self.speaker.resume()

    # ---------- 状态监控 ----------
    async def _monitor_loop(self) -> None:
        """每2秒查询音箱状态：PLAYING→IDLE 视为播完，自动下一条。"""
        while True:
            await asyncio.sleep(2)
            if not self.current:
                continue
            try:
                st = await self.speaker.status()
            except Exception:
                continue
            s = (st or {}).get("status", "")
            if s == "PLAYING":
                self._was_playing = True
            elif self._was_playing and s in ("IDLE", "STOP", "") and time.time() > self._suppress_until:
                log.info("检测到播完，自动下一个")
                self._was_playing = False
                await self._advance()

    def state(self) -> dict:
        return {
            "current": self.current,
            "position": None,
            "base_url": self.base_url,
        }
