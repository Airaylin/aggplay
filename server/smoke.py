"""冒烟测试：python -m server.smoke [--source bilibili] [--net]
- 默认：意图解析单元测试 + ffmpeg 检查
- --net：匿名连通性（B站nav/wbi）
- data/config.json 里已填 Cookie 的源会做全量 fetch+resolve 测试
"""
import asyncio
import shutil
import sys

from . import config
from .sources import all_sources


def test_intents() -> bool:
    from . import intents
    cases = [
        ("停止", {"action": "stop"}), ("别放了", {"action": "stop"}),
        ("暂停", {"action": "pause"}), ("继续播放", {"action": "resume"}),
        ("下一个", {"action": "next"}), ("上一首", {"action": "prev"}),
        ("播放我的待听", {"action": "play"}),
        ("播放稍后再看", {"action": "play"}),
        ("播放B站", {"action": "play", "source": "bilibili"}),
        ("播放网易云音乐", {"action": "play", "source": "netease"}),
        ("播放喜马拉雅", {"action": "play", "source": "ximalaya"}),
        ("播放第三个", {"action": "play", "index": 2}),
        ("播放第十二个", {"action": "play", "index": 11}),
        ("有什么内容", {"action": "list"}),
        ("今天天气怎么样", None),
        ("打开空调", None),
        ("音量调到40", {"action": "volume", "value": 40}),
    ]
    ok = True
    for text, want in cases:
        got = intents.parse(text)
        if got != want:
            print(f"  ✕ {text!r} -> {got} (期望 {want})")
            ok = False
        else:
            print(f"  ✓ {text}")
    return ok


def test_parse_share() -> bool:
    from .sources.parse import parse
    cases = [
        ("【教程】https://b23.tv/abc123 快看", ("bilibili", "https://b23.tv/abc123", "教程")),
        ("https://www.bilibili.com/video/BV1xx411c7mD", ("bilibili", "BV1xx411c7mD", "")),
        ("http://music.163.com/song?id=186016", ("netease", "186016", "")),
        ("https://www.ximalaya.com/album/123456", ("ximalaya", "album:123456", "")),
        ("https://mp.weixin.qq.com/s/xxxx", ("weread", None, None)),
        ("https://a.com/x.mp3", ("manual", None, None)),
    ]
    ok = True
    for text, (src, ref, title) in cases:
        got = parse(text)
        if not got or got.source != src or (ref and got.ref != ref) or (title and got.title != title):
            print(f"  ✕ {text!r} -> {got}")
            ok = False
        else:
            print(f"  ✓ {text[:40]}")
    return ok


def test_netease_crypto() -> bool:
    """weapi 加密自洽性：能跑通且 params/encSecKey 形态正确。"""
    from .sources.netease import _aes, _rsa
    s = _aes(_aes('{"a":1}', b"0CoJm6QQywKWWdIN"), b"1234567890abcdef")
    assert len(s) > 40, "params 过短"
    k = _rsa("1234567890abcdef")
    assert len(k) == 256, f"encSecKey 长度 {len(k)}"
    print("  ✓ weapi 加密形态正确")
    return True


async def test_sources(only: str | None, net: bool) -> None:
    cfg = config.load()
    for name, src in all_sources().items():
        if only and name != only:
            continue
        if not src.enabled(cfg):
            print(f"  - {name}: 未启用，跳过")
            continue
        try:
            items = await asyncio.to_thread(src.fetch, cfg)
            first = items[0] if items else None
            spec = await asyncio.to_thread(src.resolve, cfg, first) if first else None
            extra = f"，首条「{first.title}」" if first else ""
            extra += f" 直链={bool(spec and spec.url and not spec.tts_text)}" if spec else ""
            print(f"  ✓ {name}: {len(items)} 条{extra}")
        except Exception as e:
            print(f"  ✕ {name}: {str(e)[:160]}")


async def net_anon() -> None:
    import httpx
    from .sources.bilibili import _wbi_keys, _cookies
    cfg = config.load()
    try:
        keys = await asyncio.to_thread(_wbi_keys, cfg)
        print(f"  ✓ B站连通，wbi_keys={'OK' if keys else '匿名拿不到(正常,登录后有)'}")
    except Exception as e:
        print(f"  ✕ B站连通失败: {e}")


def main():
    only = None
    net = "--net" in sys.argv
    for i, a in enumerate(sys.argv):
        if a == "--source" and i + 1 < len(sys.argv):
            only = sys.argv[i + 1]

    print("[1] 意图解析")
    ok1 = test_intents()
    print("[2] 分享文本识别")
    ok2 = test_parse_share()
    print("[3] 网易云加密")
    ok3 = test_netease_crypto()
    print("[4] ffmpeg")
    ff = shutil.which("ffmpeg")
    print(f"  {'✓ 找到 ' + ff if ff else '✕ 未安装（流端点需要；服务器容器内自带）'}")
    if net or True:
        print("[5] 各内容源（已配置Cookie的）")
        asyncio.run(test_sources(only, net))
        if net:
            print("[6] 匿名连通性")
            asyncio.run(net_anon())
    all_ok = ok1 and ok2 and ok3
    print("结果:", "全部通过 ✅" if all_ok else "有失败项 ❌")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
