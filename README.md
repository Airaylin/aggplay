# aggplay · 聚合待听

对着小爱音箱说一句话，连续播放你在 B站/网易云/喜马拉雅/微信读书 收藏的全部内容。

## 架构

```
小爱音箱 ←→ 小米云 MiNA API
   ↑ 每秒轮询"你说了什么" / TTS回应 / player_play_url
[aggplay 主服务] ──→ B站·网易云·喜马拉雅·微信读书（带你的Cookie拉列表/解析直链）
   ├─ 意图解析（口令白名单，其余不拦截小爱原生功能）
   ├─ ffmpeg 统一转 mp3@128k（L05C 等型号不吃 flac/m4s）
   ├─ 微信读书/文章 → edge-tts 流式合成语音
   └─ 手机浏览器管理页：贴Cookie、看队列、一键测试
```

- 服务器要求：国内节点（内容平台对境外IP有地域限制），2核2G，Docker 一键起
- 语音口令、Cookie 获取方法：部署后打开管理页「帮助」标签页

## 快速开始

服务器部署见 [DEPLOY.md](DEPLOY.md)。

本地开发：

```bash
pip install -r requirements.txt   # 另需 ffmpeg（仅流端点用到）
uvicorn server.main:app --port 8094
python -m server.smoke            # 冒烟测试（意图解析/加密/分享识别/已配置的源）
```

## 目录

```
server/
  main.py          FastAPI：API + 音频流端点 + 语音指令循环
  speaker.py       小米登录/设备发现/对话轮询/TTS/play_url（移植 miservice_fork+xiaomusic）
  intents.py       语音口令 → 播放指令
  player.py        播放引擎：报幕、拉流推送、状态监控、自动连播
  transcode.py     ffmpeg 转 mp3 / edge-tts 合成（流式）
  store.py         SQLite 队列
  config.py        data/config.json 读写
  sources/         内容源适配器（每源一个文件，坏了单独修）
    bilibili.py  netease.py  ximalaya.py  weread.py  manual.py  parse.py
  web/index.html   手机管理页（单文件）
android/           安卓投递App（分享接收 + 剪贴板快投 + 一键在音箱播放）
Dockerfile · docker-compose.yml · DEPLOY.md
```

## 安卓 App（配合服务器）

- 任意 App 里 **分享 → 聚合待听** = 投递到队列
- 复制链接后下拉点 **「投递剪贴板」快捷磁贴**（Android 10+ 不允许后台读剪贴板，磁贴点一下即投）
- 首页大按钮：**让音箱立即开播**
- 手机小爱同学自定义指令「打开聚合待听」→ App 启动自动触发音箱开播（免架桥的语音触发）
