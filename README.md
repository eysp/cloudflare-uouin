# Cloudflare 优选 IP 自动更新 DNS

定时从 [api.uouin.com](https://api.uouin.com/cloudflare.html) 获取 Cloudflare 优选 IP，取排名第一的地址，通过 Cloudflare API 更新指定域名的 A 记录，并可选通过 PushPlus 推送结果。

## 文件说明

| 文件 | 说明 |
|-----|-----|
| `cf_update.py` | 主脚本，带日志轮转，从 `.env` 读取配置。**推荐使用** |
| `dnscf.py` | 精简版，配置从系统环境变量读取，适合 GitHub Actions 等 CI 环境 |
| `run.sh` | 启动包装脚本，供 systemd / cron 调用 |
| `.env` | 配置文件（含密钥，注意权限） |
| `cloudflare-dns.log` | 运行日志，每天轮转，保留 2 天（自动生成） |

## 数据源说明（重要）

`https://api.uouin.com/cloudflare.html` 的**网页源代码里的表格是 2024/04/09 的静态快照**，所有行的时间戳都是 `2024/04/09 01:42:07`。浏览器里看到的实时数据，是页面加载后由 `cloudflare.js`（jsjiami.com.v6 混淆）通过 ajax 拉取再替换 DOM 的。

因此**直接用正则解析 HTML 源码只能拿到两年前的失效 IP**，会把 DNS 更新成一个早已不可用的地址。本项目改为直接调用其后端接口：

```
GET https://api.uouin.com/index.php/index/Cloudflare?key=<md5>&time=<毫秒时间戳>

key = md5( md5("DdlTxtN0sUOu") + "70cloudflareapikey" + time )
```

返回 JSON 按线路分 5 组，均已按速度排序，取 `info[0].ip` 即为最优 IP：

| 线路 | 说明 | IP 数量 |
|-----|-----|-----|
| `bgp` | 全网通用（默认） | 10 |
| `ctcc` | 电信 | 10 |
| `cmcc` | 移动 | 10 |
| `cucc` | 联通 | 10 |
| `ipv6` | IPv6（AAAA 记录） | 5 |

签名算法是从混淆 JS 中逆向得出的。**若站方修改算法，接口将不再返回 `获取成功`，脚本会记录日志并跳过本次更新，不会写入错误 IP。**

数据源约每 10 分钟更新一次，因此更新频率设为 10 分钟以上即可，更密集没有意义。

## 配置

`.env` 文件：

```ini
CF_API_TOKEN=你的CloudflareAPIToken
CF_ZONE_ID=你的ZoneID
CF_DNS_NAME=["fdyx.example.com"]
PUSHPLUS_TOKEN=
# 优选线路: bgp(全网) / ctcc(电信) / cmcc(移动) / cucc(联通) / ipv6
IP_LINE=bgp
```

| 变量 | 必填 | 说明 |
|-----|-----|-----|
| `CF_API_TOKEN` | 是 | Cloudflare API Token，需 `Zone.DNS` 编辑权限 |
| `CF_ZONE_ID` | 是 | 域名所在 Zone 的 ID，在 Cloudflare 域名概览页右下角 |
| `CF_DNS_NAME` | 是 | JSON 数组，可写多个域名；单域名也可直接写字符串 |
| `PUSHPLUS_TOKEN` | 否 | 留空则不推送 |
| `IP_LINE` | 否 | 默认 `bgp` |

获取 API Token：Cloudflare 控制台 → 右上头像 → My Profile → API Tokens → Create Token → 用 **Edit zone DNS** 模板。

多个域名写法：

```ini
CF_DNS_NAME=["a.example.com","b.example.com"]
```

所有匹配到的记录都会被更新为同一个最优 IP。

## 前置准备

1. 在 Cloudflare 后台**手动创建一条 A 记录**（内容随便填一个 IP，如 `1.1.1.1`）。脚本只更新已存在的记录，不会创建新记录。
2. 若用 `ipv6` 线路，需创建 AAAA 记录。
3. 依赖 Python 3.6+ 和 `requests`。

## 安装

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y python3 python3-pip git
# CentOS / RHEL / Rocky
sudo yum install -y python3 python3-pip git
# Alpine
sudo apk add python3 py3-pip git

# 部署到 /opt
sudo mkdir -p /opt/cloudflare-uouin
sudo cp cf_update.py dnscf.py run.sh .env /opt/cloudflare-uouin/
cd /opt/cloudflare-uouin

# 安装依赖（新版本 pip 可能需要 --break-system-packages）
pip3 install requests

# 保护含密钥的配置
sudo chmod 600 .env
sudo chmod +x run.sh
```

推荐用虚拟环境隔离依赖：

```bash
cd /opt/cloudflare-uouin
python3 -m venv venv
./venv/bin/pip install requests
# 之后所有命令中的 python3 换成 /opt/cloudflare-uouin/venv/bin/python3
```

用 venv 时把 `run.sh` 改为：

```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/venv/bin/python3" "$SCRIPT_DIR/cf_update.py"
```

## 手动测试

```bash
cd /opt/cloudflare-uouin
python3 cf_update.py
```

正常输出：

```
2026-09-11 19:40:01,123 INFO DNS update started for: fdyx.example.com
2026-09-11 19:40:01,456 INFO Fetched 10 candidate IP(s) for line bgp, first: 104.18.37.111
2026-09-11 19:40:01,789 INFO Found 1 DNS record(s) for fdyx.example.com
2026-09-11 19:40:02,012 INFO Updated fdyx.example.com from 1.1.1.1 to 104.18.37.111
2026-09-11 19:40:02,890 INFO DNS update finished
```

确认无误后再配置定时任务。

## 部署方式一：cron（最简单，适合所有发行版）

```bash
crontab -e
```

加入（每 15 分钟执行）：

```cron
*/15 * * * * /opt/cloudflare-uouin/run.sh >/dev/null 2>&1
```

脚本自身已写日志到 `cloudflare-dns.log`，故 cron 输出丢弃即可。若想单独记录 cron 层面的错误：

```cron
*/15 * * * * /opt/cloudflare-uouin/run.sh >> /var/log/cf-dns-cron.log 2>&1
```

避开整点错峰（减少与他人同时请求）：

```cron
7,22,37,52 * * * * /opt/cloudflare-uouin/run.sh >/dev/null 2>&1
```

验证 cron 已生效：

```bash
crontab -l
sudo systemctl status cron    # Debian/Ubuntu
sudo systemctl status crond   # CentOS/RHEL
```

## 部署方式二：systemd timer（推荐，日志与状态可管理）

`/etc/systemd/system/cf-dns.service`：

```ini
[Unit]
Description=Cloudflare 优选 IP 更新 DNS
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/opt/cloudflare-uouin
ExecStart=/opt/cloudflare-uouin/run.sh
User=root

# 基础加固
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/cloudflare-uouin
```

`/etc/systemd/system/cf-dns.timer`：

```ini
[Unit]
Description=每 15 分钟更新 Cloudflare 优选 IP

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
# 随机延迟 60 秒，避免整点集中请求
RandomizedDelaySec=60
Persistent=true

[Install]
WantedBy=timers.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cf-dns.timer

# 立即手动跑一次
sudo systemctl start cf-dns.service

# 查看状态
systemctl list-timers cf-dns.timer
journalctl -u cf-dns.service -n 50 --no-pager
```

`ProtectSystem=strict` 会让整个文件系统只读，`ReadWritePaths` 放开日志目录写权限。若报权限错误，可先注释掉加固项排查。

## 部署方式三：Docker

`Dockerfile`：

```dockerfile
FROM python:3.12-alpine
WORKDIR /app
RUN pip install --no-cache-dir requests
COPY cf_update.py .
CMD ["python3", "cf_update.py"]
```

由于脚本从同目录 `.env` 读取配置，用挂载方式传入：

```bash
docker build -t cf-dns .

# 单次运行测试
docker run --rm -v /opt/cloudflare-uouin/.env:/app/.env:ro cf-dns
```

配合宿主机 cron 定时执行：

```cron
*/15 * * * * docker run --rm -v /opt/cloudflare-uouin/.env:/app/.env:ro cf-dns >/dev/null 2>&1
```

若希望容器内常驻循环，改用 `dnscf.py`（读系统环境变量）配合 `docker-compose.yml`：

```yaml
services:
  cf-dns:
    build: .
    restart: unless-stopped
    environment:
      CF_API_TOKEN: "你的Token"
      CF_ZONE_ID: "你的ZoneID"
      CF_DNS_NAME: '["fdyx.example.com"]'
      PUSHPLUS_TOKEN: ""
      IP_LINE: "bgp"
    command: >
      sh -c "while true; do python3 dnscf.py; sleep 900; done"
```

对应 `Dockerfile` 需改为 `COPY dnscf.py .`。

## 部署方式四：GitHub Actions（无服务器）

`.github/workflows/cf-dns.yml`：

```yaml
name: Update Cloudflare DNS

on:
  schedule:
    - cron: '7,37 * * * *'   # UTC 时间，每 30 分钟
  workflow_dispatch:

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install requests
      - run: python dnscf.py
        env:
          CF_API_TOKEN: ${{ secrets.CF_API_TOKEN }}
          CF_ZONE_ID: ${{ secrets.CF_ZONE_ID }}
          CF_DNS_NAME: ${{ secrets.CF_DNS_NAME }}
          PUSHPLUS_TOKEN: ${{ secrets.PUSHPLUS_TOKEN }}
          IP_LINE: bgp
```

在仓库 Settings → Secrets and variables → Actions 添加对应 secret。**注意仓库必须为私有，且不要提交 `.env`。**

GitHub Actions 的 `schedule` 在高峰期常有 5-15 分钟延迟，且长期无提交的仓库会被自动停用定时任务。对时效敏感建议用自己的服务器。

## 部署方式五：OpenWrt / 群晖

**OpenWrt**（空间紧张，建议用 `dnscf.py`）：

```bash
opkg update && opkg install python3-light python3-requests
mkdir -p /root/cf-dns && cd /root/cf-dns
# 上传 cf_update.py 和 .env

# 加入 crontab
echo '*/15 * * * * cd /root/cf-dns && python3 cf_update.py >/dev/null 2>&1' >> /etc/crontabs/root
/etc/init.d/cron restart && /etc/init.d/cron enable
```

**群晖 DSM**：控制面板 → 任务计划 → 新增 → 计划的任务 → 脚本，命令填 `bash /volume1/docker/cf-dns/run.sh`，重复设为每小时或自定义。或直接用上文 Docker 方案。

## 排障

**`KeyError: 'CF_API_TOKEN'`**
`.env` 缺少该项，或运行 `dnscf.py` 时未设置系统环境变量。`dnscf.py` 不读 `.env`，服务器上请用 `cf_update.py`。

**日志出现 `No IP found for line bgp in API response`**
接口未返回 `获取成功`。可能是签名算法被站方变更、接口地址调整或临时故障。手动验证：

```bash
python3 - <<'EOF'
import hashlib, time, urllib.request, json
m = lambda s: hashlib.md5(s.encode()).hexdigest()
t = str(int(time.time() * 1000))
key = m(m('DdlTxtN0sUOu') + '70cloudflareapikey' + t)
url = f'https://api.uouin.com/index.php/index/Cloudflare?key={key}&time={t}'
req = urllib.request.Request(url, headers={
    'Referer': 'https://api.uouin.com/cloudflare.html',
    'User-Agent': 'Mozilla/5.0'})
d = json.loads(urllib.request.urlopen(req, timeout=15).read())
print(d.get('msg'), list((d.get('data') or {}).keys()))
EOF
```

若这段也失败，说明数据源侧有变动，需重新逆向 `//static-api.urlce.com/public/js/cloudflare.js`。此时脚本不会写入错误 IP，DNS 保持原值。

**日志出现 `❌ 未找到记录`**
Cloudflare 中不存在该域名的记录，需先手动创建；也可能是 `CF_ZONE_ID` 或域名拼写有误。

**`Cloudflare DNS update failed ... code 10000`**
API Token 权限不足或已失效，确认 Token 有对应 Zone 的 `DNS:Edit` 权限。

**cron 不执行**
cron 环境的 `PATH` 很短。`run.sh` 已用绝对路径，若自行改写请写全 Python 绝对路径（`which python3` 查看）。

**IP 更新了但访问仍慢**
记录若开启了橙云（proxied），流量走 Cloudflare 边缘，改 A 记录内容不影响实际链路。优选 IP 需要记录为**灰云（DNS only）**才生效。脚本会保留记录原有的 proxied 状态，不会主动修改。

## 安全注意

- `.env` 含 Cloudflare API Token 明文，务必 `chmod 600`，且不要提交到公开仓库。
- 建议 Token 权限收窄到单个 Zone 的 DNS 编辑，不要用 Global API Key。
- 若 Token 曾出现在公开位置，去 Cloudflare 后台 Roll 掉重新生成。

## 与原版的差异

| 项 | 原版 | 本版 |
|-----|-----|-----|
| IP 来源 | `ip.164746.xyz/ipTop.html`（逗号分隔文本） | `api.uouin.com` ajax 接口（JSON，带签名） |
| 取几个 IP | 全部，按顺序分配给各记录 | 仅第 1 个，所有记录共用 |
| 线路选择 | 无 | `IP_LINE` 可选 5 种线路 |





