"""配置加载/保存：data/config.json，含所有凭据，权限 0600。"""
import hashlib
import json
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULTS = {
    "port": 8094,
    # 管理页访问口令；首次启动自动生成随机值，Web 页可改
    "admin_pass": "",
    # 生成给音箱的拉流地址前缀，如 http://1.2.3.4:8094 ；留空则每次用请求 Host 探测
    "public_base": "",
    "xiaomi": {
        "user": "",       # 小米账号
        "pass": "",       # 小米密码
        "did": "",        # 音箱设备 did（多设备时指定，留空自动取第一个音箱）
        "hardware": "",   # 硬件型号如 L05C（留空自动识别）
        "cookie": "",     # 登录失败(验证码)时手动粘贴抓包 cookie 的兜底入口
    },
    "tts_voice": "zh-CN-XiaoxiaoNeural",  # edge-tts 音色（报幕/微信读书合成用）
    "announce": True,                      # 播放前是否 TTS 报幕
    "bili_remove_after_play": False,       # 播完是否回写 B站"移出稍后再看"
    "poll_interval": 1.0,                  # 对话轮询间隔(秒)
    "sources": {
        "bilibili":  {"enabled": True,  "cookie": ""},
        "netease":   {"enabled": True,  "cookie": "", "playlists": []},  # 歌单id；空=我喜欢的音乐
        "ximalaya":  {"enabled": True,  "cookie": "", "albums": []},     # 专辑id/链接列表
        "weread":    {"enabled": True,  "cookie": "", "books": [], "articles": []},
        "manual":    {"enabled": True},
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text("utf-8"))
            cfg = _deep_merge(DEFAULTS, saved)
        except Exception:
            pass  # 损坏则回退默认
    if not cfg.get("admin_pass"):
        cfg["admin_pass"] = secrets.token_urlsafe(8)
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass  # Windows 忽略


def stream_token(cfg: dict) -> str:
    """音箱拉流 URL 里的随机段：/stream/{token}/{id}（音箱带不了 header，用不可猜路径做门禁）"""
    return hashlib.sha256(("aggplay:" + cfg["admin_pass"]).encode()).hexdigest()[:20]
