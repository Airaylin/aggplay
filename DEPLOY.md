# 部署到云服务器（首次约10分钟）

> 前提：国内轻量应用服务器（2核2G，Ubuntu 24.04 / Debian 12），控制台已放行 **TCP 8094** 和 **22** 端口。

## 1. 装 Docker

```bash
ssh root@你的服务器IP
curl -fsSL https://get.docker.com | bash -s
```

## 2. 上传代码

**方式A：git（推荐）**——把 `aggplay/` 推到你自己的私有仓库（Gitee/GitHub 均可），服务器上：

```bash
git clone https://你的私有仓库地址 /opt/aggplay
```

**方式B：scp（Windows Git Bash 里执行）**：

```bash
scp -r aggplay root@你的服务器IP:/opt/aggplay
```

## 3. 启动

```bash
cd /opt/aggplay
docker compose up -d --build
docker compose logs -f        # 看到监听 8094 即成功，Ctrl+C 退出日志
```

## 4. 初始配置（手机浏览器）

1. 打开 `http://服务器IP:8094`
2. 访问口令：服务器上执行 `cat /opt/aggplay/data/config.json` 找 `admin_pass`（页面右上角可修改）
3. **音箱页**：填小米账号密码 → 「测试登录/设备」（会显示型号如 L05C）→ 「TTS测试」（音箱会说话）
4. **内容源页**：逐个填 Cookie → 保存 → 测试 → 回到队列页点「刷新源」
5. 对音箱说：**"播放我的待听"** 🎉

## 5. 日常维护

```bash
docker logs -f aggplay              # 实时日志
cd /opt/aggplay && git pull && docker compose up -d --build   # 更新版本
```

- 所有数据（配置/队列/小米token）都在 `./data/` 目录，**换服务器只需拷走这个目录**
- 平台接口偶尔失效：哪个源坏了去内容源页点「测试」看报错，单独修对应 `server/sources/*.py`
- 促销服务器到期前留意续费价，通常换平台撸新用户价更便宜

## 安全清单

- [ ] 管理口令改成强口令（音箱页 → 修改访问口令）
- [ ] `data/` 目录不要提交到公开仓库（已写进 .gitignore）
- [ ] 各平台 Cookie 只存在你自己服务器的 `data/config.json`
- [ ] 防火墙只开 22 + 8094
