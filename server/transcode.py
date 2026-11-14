"""音频流转码/合成：
- ffmpeg：把任意直链(可带自定义请求头)统一转 mp3@128k 流式输出（L05C 不吃 flac/m4s）
- edge-tts：文本直接流式合成 mp3（报幕由音箱自带TTS负责，这里用于微信读书/文章）
"""
import asyncio
import logging
import os
from typing import AsyncIterator

log = logging.getLogger("aggplay.transcode")

FFMPEG = os.environ.get("AGGPLAY_FFMPEG", "ffmpeg")


async def ffmpeg_mp3_stream(url: str, headers: dict | None = None) -> AsyncIterator[bytes]:
    args = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin"]
    if headers:
        # ffmpeg 的 -headers 对 http(s) 输入生效
        args += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
    args += [
        "-i", url,
        "-vn", "-map", "0:a:0?",
        "-acodec", "libmp3lame", "-b:a", "128k", "-ar", "44100", "-ac", "2",
        "-f", "mp3", "pipe:1",
    ]
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        assert proc.stdout
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            yield chunk
        err = (await proc.stderr.read()).decode("utf-8", "ignore")[-500:]
        if proc.returncode not in (0, None):
            log.warning("ffmpeg 退出码 %s: %s", proc.returncode, err)
    finally:
        if proc.returncode is None:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass


async def edge_tts_mp3_stream(text: str, voice: str) -> AsyncIterator[bytes]:
    """微软 edge-tts 流式合成 mp3（免费音色，与微信读书原声不同）。"""
    import edge_tts
    communicate = edge_tts.Communicate(text, voice)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]
