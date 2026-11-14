"""小米账号登录 + 小爱音箱控制 + 对话轮询。
移植自 miservice_fork(MiAccount/MiNAService) 与 xiaomusic(conversation.py)，改用 httpx。
凭据缓存于 data/mi_token.json；账号密码触发风控时可用 config.xiaomi.cookie 手动兜底。
"""
import asyncio
import base64
import hashlib
import json
import logging
import random
import string
import time
from http.cookies import SimpleCookie
from urllib.parse import quote

import httpx

from .config import DATA_DIR

log = logging.getLogger("aggplay.speaker")

MINA_UA = (
    "MiHome/6.0.103 (com.xiaomi.mihome; build:6.0.103.1; iOS 14.4.0) "
    "Alamofire/6.0.103 MICO/iOSApp/appStore/6.0.103"
)
UA_POOL = [
    MINA_UA,
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
]

# xiaomusic/const.py 原样：对话记录接口
LATEST_ASK_API = (
    "https://userprofile.mina.mi.com/device_profile/v2/conversation"
    "?source=dialogu&hardware={hardware}&timestamp={timestamp}&limit=2"
)
# 需要走 MINA(ubus nlp_result_get) 取对话的型号
GET_ASK_BY_MINA = {"M01"}
# 播放URL必须走 player_play_music 的型号（xiaomusic/miservice NEED_USE_PLAY_MUSIC_API）
NEED_PLAY_MUSIC_API = {
    "LX04", "LX05", "L05B", "L05C", "L06", "L06A", "X08A", "X10A",
    "X08C", "X08E", "X8F", "X4B", "OH2", "OH2P", "X6A",
}

REINIT_COOLDOWN = 60
TOKEN_PATH = DATA_DIR / "mi_token.json"


def _rand(n: int) -> str:
    return "".join(random.sample(string.ascii_letters + string.digits, n))


class MiTokenStore:
    def load(self) -> dict | None:
        try:
            return json.loads(TOKEN_PATH.read_text("utf-8"))
        except Exception:
            return None

    def save(self, token: dict | None) -> None:
        if token:
            TOKEN_PATH.write_text(json.dumps(token, indent=2), "utf-8")
        elif TOKEN_PATH.exists():
            TOKEN_PATH.unlink()


class MiAccount:
    """小米账号登录：serviceLogin → serviceLoginAuth2 → serviceToken。"""

    def __init__(self, client: httpx.AsyncClient, username: str, password: str):
        self.client = client
        self.username = username
        self.password = password
        self.store = MiTokenStore()
        self.token: dict | None = self.store.load()

    async def login(self, sid: str) -> bool:
        if not self.token:
            self.token = {"deviceId": _rand(16).upper()}
        try:
            resp = await self._service_login(f"serviceLogin?sid={sid}&_json=true")
            if resp.get("code") != 0:
                data = {
                    "_json": "true",
                    "qs": resp["qs"],
                    "sid": resp["sid"],
                    "_sign": resp["_sign"],
                    "callback": resp["callback"],
                    "user": self.username,
                    "hash": hashlib.md5(self.password.encode()).hexdigest().upper(),
                }
                resp = await self._service_login("serviceLoginAuth2", data)
                if resp.get("code") != 0:
                    raise RuntimeError(f"登录被拒绝: {resp}")
            self.token["userId"] = resp["userId"]
            self.token["passToken"] = resp["passToken"]
            service_token = await self._security_token_service(
                resp["location"], resp["nonce"], resp["ssecurity"]
            )
            self.token[sid] = (resp["ssecurity"], service_token)
            self.store.save(self.token)
            return True
        except Exception as e:
            log.warning("小米登录失败(%s): %s", self.username, e)
            self.token = None
            self.store.save(None)
            return False

    async def _service_login(self, uri: str, data: dict | None = None) -> dict:
        headers = {"User-Agent": random.choice(UA_POOL)}
        cookies = {"sdkVersion": "3.9", "deviceId": self.token["deviceId"]}
        if "passToken" in self.token:
            cookies["userId"] = str(self.token["userId"])
            cookies["passToken"] = self.token["passToken"]
        else:
            cookies["passToken"] = ""
        r = await self.client.request(
            "GET" if data is None else "POST",
            "https://account.xiaomi.com/pass/" + uri,
            data=data, cookies=cookies, headers=headers,
        )
        return json.loads(r.content[11:])  # 响应以 "&&&START&&&" 开头

    async def _security_token_service(self, location: str, nonce, ssecurity: str) -> str:
        nsec = "nonce=" + str(nonce) + "&" + ssecurity
        client_sign = base64.b64encode(hashlib.sha1(nsec.encode()).digest()).decode()
        r = await self.client.get(location + "&clientSign=" + quote(client_sign))
        service_token = r.cookies.get("serviceToken")
        if not service_token:
            raise RuntimeError(f"获取 serviceToken 失败: {r.text[:200]}")
        return service_token

    async def mi_request(self, sid: str, url: str, data=None, headers=None, relogin=True):
        headers = dict(headers or {})
        headers["User-Agent"] = MINA_UA
        if (self.token and sid in self.token) or await self.login(sid):
            cookies = {
                "userId": str(self.token["userId"]),
                "serviceToken": self.token[sid][1],
            }
            content = data(self.token, cookies) if callable(data) else data
            r = await self.client.request(
                "GET" if data is None else "POST",
                url, data=content, cookies=cookies, headers=headers,
            )
            status, resp = r.status_code, None
            if status == 200:
                resp = r.json()
                if resp.get("code") == 0:
                    return resp
                if "auth" in str(resp.get("message", "")).lower():
                    status = 401
            if status == 401 and relogin:
                log.info("鉴权失效，重新登录: %s", url)
                self.token = None
                self.store.save(None)
                return await self.mi_request(sid, url, data, headers, False)
            raise RuntimeError(f"请求失败({status}) {url}: {resp}")
        raise RuntimeError("小米登录失败：检查账号密码；若触发验证码请在配置里填抓包 cookie")


class MiNAService:
    """小爱音箱 MINA 接口（api2.mina.mi.com，sid=micoapi）。"""

    def __init__(self, account: MiAccount | None, client: httpx.AsyncClient):
        self.account = account          # None = 手动cookie模式
        self.client = client
        self.device2hardware: dict[str, str] = {}

    async def mina_request(self, uri: str, data: dict | None = None) -> dict:
        request_id = "app_ios_" + _rand(30)
        if data is not None:
            data = dict(data)
            data["requestId"] = request_id
        else:
            uri += "&requestId=" + request_id
        headers = {"User-Agent": MINA_UA}
        if self.account is not None:
            return await self.account.mi_request(
                "micoapi", "https://api2.mina.mi.com" + uri, data, headers
            )
        # 手动cookie模式：cookie 已在 client 里
        r = await self.client.request(
            "GET" if data is None else "POST",
            "https://api2.mina.mi.com" + uri, data=data, headers=headers,
        )
        r.raise_for_status()
        resp = r.json()
        if resp.get("code") != 0:
            raise RuntimeError(f"mina请求失败: {resp}")
        return resp

    async def device_list(self) -> list[dict]:
        return (await self.mina_request("/admin/v2/device_list?master=0")).get("data") or []

    async def ubus_request(self, device_id: str, method: str, path: str, message: dict) -> dict:
        return await self.mina_request("/remote/ubus", {
            "deviceId": device_id,
            "message": json.dumps(message),
            "method": method,
            "path": path,
        })

    # ---- TTS / 播放控制 ----
    async def text_to_speech(self, device_id: str, text: str) -> dict:
        return await self.ubus_request(device_id, "text_to_speech", "mibrain", {"text": text})

    async def player_set_volume(self, device_id: str, volume: int) -> dict:
        return await self.ubus_request(device_id, "player_set_volume", "mediaplayer",
                                       {"volume": volume, "media": "app_ios"})

    async def player_pause(self, device_id: str) -> dict:
        return await self.ubus_request(device_id, "player_play_operation", "mediaplayer",
                                       {"action": "pause", "media": "app_ios"})

    async def player_stop(self, device_id: str) -> dict:
        return await self.ubus_request(
            device_id, "player_play_operation", "mediaplayer",
            {"action": "stop", "media": "app_ios"})

    async def player_play(self, device_id: str) -> dict:
        return await self.ubus_request(device_id, "player_play_operation", "mediaplayer",
                                       {"action": "play", "media": "app_ios"})

    async def player_get_status(self, device_id: str) -> dict:
        """返回解析后的 {"status": "PLAYING"|...}"""
        result = await self.ubus_request(device_id, "player_get_play_status",
                                         "mediaplayer", {"media": "app_ios"})
        info = (result.get("data") or {}).get("info")
        if isinstance(info, str):
            try:
                return json.loads(info)
            except Exception:
                return {}
        return info or {}

    async def play_by_url(self, device_id: str, url: str, _type: int = 2) -> dict:
        """让音箱播放任意URL。L05C等型号走 player_play_music 兼容通道。"""
        if device_id not in self.device2hardware:
            for d in await self.device_list():
                did, hw = d.get("deviceID", ""), d.get("hardware", "")
                if did and hw:
                    self.device2hardware[did] = hw
        hardware = self.device2hardware.get(device_id, "")
        if hardware in NEED_PLAY_MUSIC_API:
            return await self.play_by_music_url(device_id, url, _type)
        return await self.ubus_request(device_id, "player_play_url", "mediaplayer",
                                       {"url": url, "type": _type, "media": "app_ios"})

    async def play_by_music_url(self, device_id: str, url: str, _type: int = 2,
                                audio_id: str = "1582971365183456177",
                                cp_id: str = "355454500") -> dict:
        audio_type = "MUSIC" if _type == 1 else ""
        music = {
            "payload": {
                "audio_type": audio_type,
                "audio_items": [{
                    "item_id": {
                        "audio_id": audio_id,
                        "cp": {"album_id": "-1", "episode_index": 0,
                               "id": cp_id, "name": "xiaowei"},
                    },
                    "stream": {"url": url},
                }],
                "list_params": {"listId": "-1", "loadmore_offset": 0,
                                "origin": "xiaowei", "type": "MUSIC"},
            },
            "play_behavior": "REPLACE_ALL",
        }
        return await self.ubus_request(device_id, "player_play_music", "mediaplayer", {
            "startaudioid": audio_id, "music": json.dumps(music)})

    # ---- 对话记录（仅 M01 等特殊型号走这条路）----
    async def get_latest_ask(self, device_id: str) -> list[dict]:
        result = await self.ubus_request(device_id, "nlp_result_get", "mibrain", {})
        data = result.get("data") or {}
        if data.get("code") != 0 or not data.get("info"):
            return []
        out = []
        for item in json.loads(data["info"]).get("result", []):
            nlp = item.get("nlp")
            if not nlp:
                continue
            try:
                nlp = json.loads(nlp)
                meta = nlp.get("meta", {})
                for a in nlp.get("response", {}).get("answer", []):
                    out.append({
                        "time": int(meta.get("timestamp", 0)),
                        "query": a.get("intention", {}).get("query", ""),
                        "answer": a.get("content", {}).get("to_speak", ""),
                    })
            except Exception:
                continue
        return out


class SpeakerError(Exception):
    pass


class Speaker:
    """对外门面：登录、选设备、轮询对话、TTS、播放控制。"""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.client = httpx.AsyncClient(verify=False, timeout=httpx.Timeout(15), http2=False)
        self.account: MiAccount | None = None
        self.mina: MiNAService | None = None
        self.device_id: str = ""      # MINA deviceID
        self.did: str = ""            # MIoT did
        self.hardware: str = ""
        self.manual_cookie = False
        self._ready = False
        self._last_ts = 0
        self._last_reinit = 0.0

    # ---- 登录/设备 ----
    async def ensure_ready(self, force: bool = False) -> dict:
        if self._ready and not force:
            return {"device_id": self.device_id, "did": self.did, "hardware": self.hardware}
        x = self.cfg["xiaomi"]
        manual_cookie = (x.get("cookie") or "").strip()
        if manual_cookie and not (x.get("user") and x.get("pass")):
            self._use_manual_cookie(manual_cookie)
        else:
            self.account = MiAccount(self.client, x.get("user", ""), x.get("pass", ""))
            self.mina = MiNAService(self.account, self.client)
            if not await self.account.login("micoapi"):
                if manual_cookie:
                    self._use_manual_cookie(manual_cookie)
                else:
                    raise SpeakerError("小米登录失败（账号密码错误或触发验证码；可在配置填抓包cookie兜底）")
        devices = await self.mina.device_list()
        if not devices:
            raise SpeakerError("账号下没有小爱音箱设备")
        device = None
        for d in devices:
            if x.get("did") and d.get("miotDID") in (x["did"], str(x["did"])):
                device = d
                break
            if x.get("hardware") and d.get("hardware") == x["hardware"]:
                device = d
                break
        device = device or devices[0]
        self.device_id = device.get("deviceID", "")
        self.did = str(device.get("miotDID", "") or device.get("did", ""))
        self.hardware = device.get("hardware", "")
        self.mina.device2hardware[self.device_id] = self.hardware
        self._last_ts = int(time.time() * 1000)
        self._ready = True
        log.info("音箱就绪: %s hardware=%s did=%s manual_cookie=%s",
                 device.get("name", ""), self.hardware, self.did, self.manual_cookie)
        return {"device_id": self.device_id, "did": self.did, "hardware": self.hardware}

    def _use_manual_cookie(self, cookie_str: str) -> None:
        """手动cookie兜底：形如 userId=123; serviceToken=xxx"""
        jar = SimpleCookie()
        jar.load(cookie_str if "=" in cookie_str else f"x={cookie_str}")
        for k, v in jar.items():
            self.client.cookies.set(k, v.value, domain=".mina.mi.com")
        self.account = None
        self.mina = MiNAService(None, self.client)
        self.manual_cookie = True

    async def relogin_if_needed(self, err_text: str) -> bool:
        """401/70016 时带冷却地强制重登。"""
        if not any(s in err_text for s in ("401", "70016", "Login failed", "鉴权失效")):
            return False
        if time.time() - self._last_reinit < REINIT_COOLDOWN:
            return False
        self._last_reinit = time.time()
        self._ready = False
        await self.ensure_ready(force=True)
        return True

    # ---- 对话轮询 ----
    async def poll_loop(self, on_query) -> None:
        """每秒拉一次最新对话；发现新语句回调 on_query(text)。"""
        await self.ensure_ready()
        interval = float(self.cfg.get("poll_interval", 1.0))
        while True:
            try:
                await self._poll_once(on_query)
            except Exception as e:
                log.warning("对话轮询异常: %s", e)
                await self.relogin_if_needed(str(e))
            await asyncio.sleep(interval)

    async def _poll_once(self, on_query) -> None:
        if self.hardware in GET_ASK_BY_MINA:
            records = await self.mina.get_latest_ask(self.device_id)
        else:
            url = LATEST_ASK_API.format(
                hardware=self.hardware, timestamp=int(time.time() * 1000))
            cookie = (f"deviceId={self.device_id}; "
                      f"serviceToken={self._service_token()}; userId={self._user_id()}")
            r = await self.client.get(url, headers={"Cookie": cookie,
                                                    "User-Agent": MINA_UA})
            if r.status_code == 401:
                raise RuntimeError("conversation 401")
            data = (r.json() or {}).get("data")
            records = json.loads(data).get("records", []) if data else []
        for rec in records:
            ts, query = int(rec.get("time", 0)), (rec.get("query") or "").strip()
            if ts > self._last_ts and query:
                self._last_ts = ts
                log.info("捕获语音指令: %s", query)
                asyncio.create_task(on_query(query))

    def _service_token(self) -> str:
        if self.account and self.account.token and "micoapi" in self.account.token:
            return self.account.token["micoapi"][1]
        return self.client.cookies.get("serviceToken", "")

    def _user_id(self) -> str:
        if self.account and self.account.token:
            return str(self.account.token.get("userId", ""))
        return self.client.cookies.get("userId", "")

    # ---- 控制接口 ----
    async def tts(self, text: str) -> None:
        await self.ensure_ready()
        await self.mina.text_to_speech(self.device_id, text)

    async def play_url(self, url: str) -> None:
        await self.ensure_ready()
        await self.mina.play_by_url(self.device_id, url, 2)

    async def pause(self) -> None:
        await self.mina.player_pause(self.device_id)

    async def resume(self) -> None:
        await self.mina.player_play(self.device_id)

    async def stop(self) -> None:
        await self.mina.player_stop(self.device_id)

    async def status(self) -> dict:
        await self.ensure_ready()
        try:
            return await self.mina.player_get_status(self.device_id)
        except Exception:
            return {}

    async def set_volume(self, volume: int) -> None:
        await self.mina.player_set_volume(self.device_id, max(0, min(100, int(volume))))
