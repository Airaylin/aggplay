# aggplay「聚合待听」· PRD 需求开发文档

> 版本 v1.0 ｜ 2026-11-15 ｜ 供 AI IDE（Trae 等）开发/二开的完整需求基线
> 本目录附带一套**可运行的参考实现**（server/ + android/），可作为对照：改 bug、补功能、或按本文档重写均可。

---

## 1. 背景与目标

### 1.1 问题
用户在各平台（B站稍后再看、网易云歌单、喜马拉雅订阅、微信读书书架/公众号文章）积累了大量"想听"的内容，但消费时需要在多个 App 间手动点选，无法"躺着一句话全播完"。

### 1.2 产品目标
一个**部署在国内云服务器上的个人聚合播放服务** + 一个**安卓投递App**，实现：

1. **语音点播**：对小爱音箱（小米小爱音箱 Play 增强版 L05C）说「播放我的待听」，约 2 秒后音箱开始连续播放聚合队列；播放中可语音控制下一首/暂停/第N个等
2. **免手投递**：手机任意 App 里"分享 → 聚合待听"即加入队列；或复制链接后点通知栏磁贴一键投递
3. **自动流转**：播完自动接下一条；B站条目可选播完自动移出"稍后再看"

### 1.3 明确不做的（v1 边界）
- ❌ 不做视频画面（音箱只出声）
- ❌ 不做 iOS/PC 客户端
- ❌ 不做公网多用户/SaaS——单用户自部署
- ❌ 不抢小爱原生技能：不在口令表里的话不拦截

---

## 2. 用户与核心场景

**用户画像**：单一用户（机主），手机 + 小爱音箱 + 云服务器。

| # | 场景 | 期望行为 |
|---|------|---------|
| S1 | 躺沙发想听内容 | 对音箱说「播放我的待听」→ TTS报幕 → 连播全队列 |
| S2 | 只想听某一类 | 「播放B站」/「播放喜马拉雅」→ 只播该源 |
| S3 | 刷手机看到好视频 | B站App 分享→聚合待听 → 内容进入队列 |
| S4 | 复制了链接 | 下拉通知栏点「投递剪贴板」磁贴 → 秒入队 |
| S5 | 播放中想跳过 | 「下一个」/「播放第三个」/「播放 流浪地球」 |
| S6 | 想知道有什么 | 「有什么内容」→ TTS 播报各源条数摘要 |
| S7 | 出门在外管理 | 手机浏览器开管理页看队列/投递/测试 |

---

## 3. 系统架构

```
小爱音箱 ←→ 小米云 MiNA/MiIO API
   ↑ 1s轮询对话记录 / TTS播报 / player_play_url 推流
[aggplay 主服务 (Python/FastAPI, 端口8094, Docker部署)]
   ├─ speaker.py   小米账号登录+设备发现+对话轮询+TTS+播放控制
   ├─ intents.py   语音口令 → 结构化指令（白名单，不匹配不拦截）
   ├─ player.py    播放引擎：报幕/选条/推送/状态监控/自动连播
   ├─ transcode.py ffmpeg 流式转码 mp3@128k / edge-tts 文本合成
   ├─ store.py     SQLite 队列（status: pending/playing/played/failed）
   ├─ config.py    data/config.json 凭据存储（0600）
   └─ sources/     源适配器（每源独立文件，坏了单独修）
        bilibili.py  netease.py  ximalaya.py  weread.py  manual.py  parse.py
[安卓App (Kotlin, 零第三方依赖)]
   MainActivity   WebView管理页 + 一键开播按钮 + 可选"打开自动开播"
   ShareActivity  接收系统分享文本 → POST /api/add
   ClipboardGrabActivity + QuickTile  磁贴→透明页读剪贴板→投递
```

**端到端关键链路**（最高风险项，最先打通）：
对话轮询(userprofile.mina.mi.com) → 意图解析 → TTS回应 → 让音箱拉 `http://服务器IP:8094/stream/{token}/{itemId}` → 播放状态轮询判定播完 → 自动下一条。

---

## 4. 功能需求

### FR-1 语音指令（intents）
| 口令（口语等价均支持） | 指令 |
|---|---|
| 播放我的待听 / 播放稍后再看 / 播放全部 | play(全队列) |
| 播放B站 / 网易云 / 喜马拉雅 / 微信读书 | play(source) |
| 播放第N个（含中文数字「第三个」「第十二个」） | play(index) |
| 播放xxx标题 | play(query 模糊匹配) |
| 下一个/下一首/下一集/跳过 ｜ 上一个 | next / prev |
| 暂停/停一下 ｜ 继续/接着放 ｜ 停止/别放了 | pause / resume / stop |
| 有什么内容 / 我的待听有哪些 | list（TTS报各源条数） |
| 音量大一点/小一点 ｜ 音量调到40 | volume ±10 / 绝对值 |

约束：中文数字转换支持 1-99；正则全匹配防误触（如「打开空调」绝不命中）。

### FR-2 内容源适配器（每源：fetch 列表 + resolve 直链）
| 源 | fetch | resolve | 备注 |
|---|---|---|---|
| bilibili | 稍后再看 `x/v2/history/toview`（SESSDATA） | playurl(fnval=16)→DASH音频m4s，带Referer代理；WBI签名（mixin表+md5） | L05C不吃m4s/flac → 强制转mp3 |
| netease | 我喜欢的音乐 / 指定歌单（MUSIC_U cookie） | weapi `song/enhance/player/url/v1`；**纯Python实现 AES双重CBC+RSA 反序加密**，无需Node | VIP歌需账号有会员 |
| ximalaya | 指定专辑trackId列表（albums配置） | mobile playpage v3 → playPathAacv164 等，按优先级回退 | VIP需网页cookie(1_x_x) |
| weread | 配置的文章URL列表 / 书ID(实验) | 公众号正文抓取(#js_content) → edge-tts 流式合成 mp3 | 非微信读书原声；书章节为实验性 |
| manual | 无固定列表 | 直链 mp3/m4a 直接转发 | 只经分享/粘贴入队 |
| parse | 分享文本智能识别：BV号/av号/b23.tv、163 song id、ximalaya track/album、mp.weixin、直链音频、兜底任意URL→webarticle | | 手机App与粘贴入口共用 |

### FR-3 播放引擎（player）
- 选条优先级：item_id > query > index > source > 队列头
- 播放前 TTS 报幕（可关）：「第N条，共M条。{标题}」
- 推流后 2s 间隔轮询播放状态；PLAYING→IDLE 且过了8s起播保护窗 → 判定播完 → 自动下一条
- 解析失败自动跳下一条（同一条目连败3次标记 failed）
- 播完回写：B站可选 del toview（需bili_jct）

### FR-4 音频流端点
`GET /stream/{token}/{item_id}` → StreamingResponse：
- tts_text 存在 → edge-tts 合成流
- 否则 → ffmpeg 子进程转 mp3@128k 流式输出（-headers 注入 Referer/UA）
- token = sha256(admin_pass)[:20]（音箱无法带header，用不可猜路径做门禁）

### FR-5 Web 管理页（单文件 index.html，手机优先）
四标签：队列（播放控制/投递框/列表）、内容源（5源启用+Cookie表单+逐源测试）、音箱（小米账密/cookie兜底/对外地址/报幕开关/音色/改口令/TTS测试）、帮助（口令表+Cookie获取教程）。口令存 localStorage，Header `X-Admin-Pass` 鉴权。

### FR-6 安卓App
- 首次启动：对话框填服务器地址+口令（SharedPreferences）
- 主页：WebView 加载管理页 + 顶部大按钮 POST /api/play
- 分享接收：ACTION_SEND text/* → POST /api/add（"added":0 时提示重复）
- 快捷磁贴「投递剪贴板」：TileService → 透明 Activity（短暂获焦合法读剪贴板）→ 投递
- 可选「打开自动开播」开关：手机小爱同学自定义指令「打开聚合待听」→ 打开App即 POST /api/play（免架桥语音触发）
- **零第三方依赖**（纯平台 API + HttpURLConnection），GitHub Actions 云端打包 debug APK

### FR-7 配置与安全
- data/config.json（0600）：admin_pass 首启自动生成随机、xiaomi 账密/手动cookie兜底、各源cookie、public_base、poll_interval
- 小米token缓存 data/mi_token.json；401/70016 带冷却重登
- 管理页口令改密；Docker 只暴露 8094；服务器防火墙仅 22+8094

---

## 5. 非功能需求
| 维度 | 要求 |
|---|---|
| 语音响应延迟 | 说完口令 → TTS回应 ≤ 4s（轮询1s+解析+推流） |
| 起播延迟 | 推流后 ≤ 5s 出声（含转码启动） |
| 并发 | 单用户即可；流端点 ffmpeg 进程随播放生命周期 |
| 稳定性 | 每源接口故障隔离（独立适配器），不影响其他源 |
| 部署 | 国内2核2G轻量服务器；Docker Compose 一键起；ffmpeg容器内置 |
| 数据 | 全部本地（SQLite+JSON）；换机只拷 data/ |

---

## 6. API 规范（均已实现，可直接复用）

| 方法/路径 | 说明 |
|---|---|
| GET `/` | 管理页 |
| GET `/api/state` | 队列+当前+计数+刷新状态（Header 鉴权，下同） |
| POST `/api/config` | 合并更新配置（xiaomi/sources/public_base/announce/...；new_admin_pass 改口令） |
| GET `/api/sources_cfg` · `/api/spk_cfg` | 配置读取（密码不回传） |
| POST `/api/refresh` | 全源刷新入队 |
| POST `/api/play` {index,source,id,query} | 选条开播（返回 TTS 文案） |
| POST `/api/control/{next\|prev\|pause\|resume\|stop}` | 播放控制 |
| POST `/api/add` {text} | 分享文本→识别→入队（专辑自动展开） |
| POST `/api/clear` {what,source} | 清已听/清队列 |
| GET `/api/smoke?source=` | 单源 fetch+resolve 冒烟 |
| GET `/api/speaker/devices` · POST `/api/speaker/test_tts` | 登录设备测试 / TTS测试 |
| GET `/stream/{token}/{id}` | 音频流（音箱拉取，路径token门禁） |

---

## 7. 数据模型（SQLite `items` 表）
```
id INTEGER PK ｜ source TEXT ｜ kind TEXT ｜ title TEXT ｜ sub TEXT
ref TEXT(源内唯一: bvid/songId/trackId/URL) ｜ status TEXT(pending|playing|played|failed)
created_at REAL ｜ played_at REAL
唯一索引: (source,ref) WHERE status='played'   ← 已听不重复入队
```

---

## 8. 技术栈与约束
- 服务端：Python 3.12 + FastAPI + httpx + pycryptodome + edge-tts + bs4 + ffmpeg（容器内 apt 安装）
- 安卓：Kotlin，minSdk 26 / targetSdk 34，**禁用第三方依赖**（历史教训：CI 上 appcompat 资源链接异常，零依赖后构建100%稳定）
- 构建：GitHub Actions（ubuntu-latest 自带 Android SDK），`android/` 目录 push 即出 APK artifact
- 参考（不要复制进仓库，仅研究用）：miservice_fork、xiaomusic 的对话轮询/播放API调用方式

---

## 9. 里程碑与验收

| 里程碑 | 内容 | 验收标准 |
|---|---|---|
| M1 服务骨架+管理页 | main/config/store/web | 服务启动，全部API自测通过 |
| M2 小米链路 | speaker.py | 测试登录→设备列表出L05C→TTS出声→play_url推mp3出声 |
| M3 语音闭环 | intents+player+stream | 说「播放我的待听」≤4s回应并起播；「下一个」生效；连播3条不断 |
| M4 四源接入 | sources/* | 每源smoke通过（拉列表+直链+起播） |
| M5 安卓App | android/ | 分享投递/磁贴投递/一键开播三项实测通过 |
| M6 部署 | Dockerfile/DEPLOY.md | 服务器 up -d 后按文档10分钟全流程走通 |

## 10. 已知风险与对策
| 风险 | 对策 |
|---|---|
| 小米登录触发验证码/风控 | token缓存复用；cookie手动兜底；带冷却重登 |
| 平台接口改版 | 适配器隔离+smoke脚本定位；改单个文件修复 |
| L05C不支持flac/m4s | 服务端统一ffmpeg转mp3@128k |
| 境外IP内容受限 | 服务器必须国内节点（腾讯/阿里轻量） |
| 后台读剪贴板被Android 10+禁止 | 磁贴→透明页短暂获焦合法读取（非无障碍绕过） |

## 11. 当前实现状态（参考实现已达标项）
✅ M1-M4 全部完成（本机冒烟：意图17/17、分享识别6/6、weapi加密✓、API全通）
✅ M5 代码完成 + APK已产出（GitHub Actions）
⏳ M6 等用户服务器到位后实测；⏳ 音箱端到端（M3的真实场景验收）待部署后进行
