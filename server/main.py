"""FastAPI 主服务：管理页 + API + 音频流端点 + 语音指令循环。"""
import asyncio
import logging
import socket
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from . import config, intents
from .player import Player, SOURCE_NAMES
from .speaker import Speaker, SpeakerError
from .store import Store
from .sources import all_sources
from .sources.parse import parse as parse_share
from .sources.ximalaya import XimalayaSource
from .transcode import edge_tts_mp3_stream, ffmpeg_mp3_stream

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("aggplay")

cfg = config.load()
store = Store()
speaker = Speaker(cfg)
player = Player(cfg, store, speaker)
app = FastAPI(title="aggplay")

WEB_DIR = Path(__file__).parent / "web"
REFRESH_STATUS: dict[str, dict] = {}   # source -> {"added": n, "error": str|None, "ts": t}


# ---------- 基础 ----------
def _detect_base() -> str:
    if cfg.get("public_base"):
        return cfg["public_base"].rstrip("/")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return f"http://{ip}:{cfg['port']}"


def _auth(x_admin_pass: str = Header(default="")) -> None:
    if x_admin_pass != cfg["admin_pass"]:
        raise HTTPException(401, "口令错误（请在页面右上角设置访问口令）")


# ---------- 语音指令 ----------
def _summary() -> str:
    counts = store.counts()
    parts = [f"{SOURCE_NAMES.get(s, s)}{sum(v.values())}条" for s, v in counts.items()
             if sum(v.values()) > 0]
    txt = "待听队列：" + ("，".join(parts) if parts else "空的")
    if player.current:
        txt += f"。正在播：{(player.current.get('title') or '')[:20]}"
    return txt[:120]


async def on_query(text: str) -> None:
    intent = intents.parse(text)
    log.info("语音指令: %r -> %s", text, intent)
    if not intent:
        return  # 不是我们的口令，不抢小爱原生功能
    try:
        act = intent.get("action")
        if act == "play":
            say = await player.play(index=intent.get("index"),
                                    source=intent.get("source"),
                                    item_id=intent.get("item_id"),
                                    query=intent.get("query"))
            if not cfg.get("announce", True):
                await speaker.tts(say)
        elif act == "stop":
            await player.stop()
        elif act == "pause":
            await player.pause()
        elif act == "resume":
            await player.resume()
        elif act == "next":
            await player.next()
        elif act == "prev":
            await player.prev()
        elif act == "list":
            await speaker.tts(_summary())
        elif act == "volume":
            st = await speaker.status()
            cur = int(st.get("volume", 30) or 30)
            v = intent.get("value")
            vol = max(0, min(100, cur + int(v))) if isinstance(v, str) else int(v)
            await speaker.set_volume(vol)
    except Exception as e:
        log.exception("指令执行失败")
        try:
            await speaker.tts(f"出了点问题，{str(e)[:28]}")
        except Exception:
            pass


async def _voice_loop() -> None:
    x = cfg.get("xiaomi", {})
    if not (x.get("user") and x.get("pass")) and not x.get("cookie"):
        log.warning("未配置小米账号，语音功能未启动（管理页-音箱 设置后自动生效）")
        while not (x.get("user") and x.get("pass")) and not x.get("cookie"):
            await asyncio.sleep(10)
            x = cfg.get("xiaomi", {})
    while True:
        try:
            await speaker.poll_loop(on_query)
        except Exception as e:
            log.warning("语音循环异常: %s，30秒后重试", e)
            await asyncio.sleep(30)


@app.on_event("startup")
async def _startup() -> None:
    player.base_url = _detect_base()
    log.info("对外拉流地址: %s", player.base_url)
    asyncio.create_task(player.start())
    asyncio.create_task(_voice_loop())


# ---------- 页面 ----------
@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


# ---------- API ----------
@app.get("/api/state")
async def api_state(x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    return {"queue": store.list(), "current": player.current,
            "counts": store.counts(), "refresh": REFRESH_STATUS,
            "base": player.base_url}


@app.post("/api/config")
async def api_config(body: dict, x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    global cfg
    new_pass = body.pop("new_admin_pass", None)
    cfg = config._deep_merge(cfg, body)
    if new_pass:
        cfg["admin_pass"] = new_pass
    config.save(cfg)
    speaker.cfg = cfg
    player.cfg = cfg
    return {"ok": True, "admin_pass": cfg["admin_pass"]}


@app.get("/api/sources_cfg")
async def api_sources_cfg(x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    return cfg["sources"]


@app.get("/api/spk_cfg")
async def api_spk_cfg(x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    x = dict(cfg["xiaomi"])
    x.pop("pass", None)  # 密码不回传前端
    return {"xiaomi": x, "public_base": cfg.get("public_base", ""),
            "announce": cfg.get("announce", True),
            "bili_remove": cfg.get("bili_remove_after_play", False),
            "tts_voice": cfg.get("tts_voice", "zh-CN-XiaoxiaoNeural")}


@app.post("/api/refresh")
async def api_refresh(x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    results = {}
    for name, src in all_sources().items():
        if not src.enabled(cfg):
            results[name] = {"error": "未启用"}
            continue
        def _fetch(s=src):
            items = s.fetch(cfg)
            return store.replace_source(name, [i.__dict__ for i in items])
        try:
            added = await asyncio.wait_for(asyncio.to_thread(_fetch), 90)
            REFRESH_STATUS[name] = {"added": added, "error": None}
        except Exception as e:
            REFRESH_STATUS[name] = {"added": 0, "error": str(e)[:200]}
        results[name] = REFRESH_STATUS[name]
    return results


class PlayBody(BaseModel):
    index: int | None = None
    source: str | None = None
    id: int | None = None
    query: str | None = None


@app.post("/api/play")
async def api_play(body: PlayBody, x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    say = await player.play(index=body.index, source=body.source,
                            item_id=body.id, query=body.query)
    return {"ok": True, "say": say}


@app.post("/api/control/{action}")
async def api_control(action: str, x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    if action == "next":
        await player.next()
    elif action == "prev":
        await player.prev()
    elif action == "pause":
        await player.pause()
    elif action == "resume":
        await player.resume()
    elif action == "stop":
        await player.stop()
    else:
        raise HTTPException(400, f"未知操作 {action}")
    return {"ok": True}


class AddBody(BaseModel):
    text: str


@app.post("/api/add")
async def api_add(body: AddBody, x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    item = parse_share(body.text)
    if not item:
        return {"ok": False, "error": "没识别出内容（支持B站/网易云/喜马拉雅链接、公众号文章、mp3直链）"}
    if item.source == "ximalaya" and item.ref.startswith("album:"):
        album = item.ref.split(":", 1)[1]

        def _expand():
            return XimalayaSource().album_tracks(album)
        try:
            tracks = await asyncio.wait_for(asyncio.to_thread(_expand), 60)
        except Exception as e:
            return {"ok": False, "error": f"专辑展开失败: {e}"}
        n = 0
        for t in tracks:
            if store.add(t.source, t.ref, t.title, t.sub, t.kind):
                n += 1
        return {"ok": True, "added": n, "title": f"专辑{album}共{n}条"}
    new_id = store.add(item.source, item.ref, item.title, item.sub, item.kind)
    return {"ok": new_id is not None, "added": 1 if new_id else 0, "item": item.__dict__}


class ClearBody(BaseModel):
    what: str = "played"
    source: str | None = None


@app.post("/api/clear")
async def api_clear(body: ClearBody, x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    store.clear(body.what, body.source)
    return {"ok": True}


@app.get("/api/smoke")
async def api_smoke(source: str | None = None, x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    out = {}
    for name, src in all_sources().items():
        if source and name != source:
            continue
        if not src.enabled(cfg):
            out[name] = {"ok": False, "error": "未启用"}
            continue
        def _fetch(s=src):
            items = s.fetch(cfg)
            first = items[0] if items else None
            spec = s.resolve(cfg, first) if first else None
            return len(items), first.title if first else "", bool(spec and not spec.tts_text)
        try:
            n, title, has_url = await asyncio.wait_for(asyncio.to_thread(_fetch), 90)
            out[name] = {"ok": True, "count": n, "first": title, "first_has_url": has_url}
        except Exception as e:
            out[name] = {"ok": False, "error": str(e)[:200]}
    return out


@app.get("/api/speaker/devices")
async def api_devices(x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    try:
        info = await asyncio.wait_for(speaker.ensure_ready(force=True), 30)
        st = await speaker.status()
        return {"ok": True, "device": info, "status": st}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


class TTSBody(BaseModel):
    text: str = "聚合待听已就绪"


@app.post("/api/speaker/test_tts")
async def api_tts(body: TTSBody, x_admin_pass: str = Header(default="")):
    _auth(x_admin_pass)
    try:
        await asyncio.wait_for(speaker.tts(body.text), 20)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


# ---------- 音频流（音箱拉这里，token 门禁）----------
@app.get("/stream/{token}/{item_id}")
async def api_stream(token: str, item_id: int):
    from .config import stream_token
    if token != stream_token(cfg):
        raise HTTPException(403)
    row = store.get(item_id)
    if not row:
        raise HTTPException(404)
    spec = player._spec_cache.get(item_id)
    if spec is None:
        try:
            spec = await asyncio.wait_for(asyncio.to_thread(player._resolve, row), 40)
            player._spec_cache[item_id] = spec
        except Exception as e:
            log.warning("流端点解析失败 %s: %s", item_id, e)
            raise HTTPException(502, str(e)[:200])
    if spec.tts_text:
        return StreamingResponse(edge_tts_mp3_stream(spec.tts_text, cfg.get("tts_voice", "")),
                                 media_type="audio/mpeg")
    return StreamingResponse(ffmpeg_mp3_stream(spec.url, spec.headers),
                             media_type="audio/mpeg")
