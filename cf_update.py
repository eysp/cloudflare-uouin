import requests
import hashlib
import time
import os
import json
import logging
from logging.handlers import TimedRotatingFileHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_env_file():
    path = os.path.join(BASE_DIR, ".env")
    with open(path, encoding="utf-8") as env_file:
        for line in env_file:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                os.environ.setdefault(name.strip(), value.strip())

load_env_file()

logger = logging.getLogger("cloudflare-dns")
logger.setLevel(logging.INFO)
handler = TimedRotatingFileHandler(
    os.path.join(BASE_DIR, "cloudflare-dns.log"),
    when="midnight",
    backupCount=2,
    encoding="utf-8",
)
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logger.addHandler(handler)
logger.addHandler(logging.StreamHandler())

CF_API_TOKEN = os.environ["CF_API_TOKEN"]
CF_ZONE_ID = os.environ["CF_ZONE_ID"]
CF_DNS_NAME = os.environ["CF_DNS_NAME"]
PUSHPLUS_TOKEN = os.environ["PUSHPLUS_TOKEN"]
# 优选线路: bgp(默认/全网) / ctcc(电信) / cmcc(移动) / cucc(联通) / ipv6
IP_LINE = os.environ.get("IP_LINE", "bgp").strip() or "bgp"

try:
    CF_DNS_NAME = json.loads(CF_DNS_NAME)
except:
    CF_DNS_NAME = [CF_DNS_NAME]

headers = {
    'Authorization': f'Bearer {CF_API_TOKEN}',
    'Content-Type': 'application/json'
}

IP_PAGE_URL = 'https://api.uouin.com/cloudflare.html'
# cloudflare.html 里的表格是 2024 年的静态快照，真实数据由页面的 ajax 拉取；
# 签名算法取自 //static-api.urlce.com/public/js/cloudflare.js
IP_API_URL = 'https://api.uouin.com/index.php/index/Cloudflare'
IP_API_SALT = 'DdlTxtN0sUOu'
IP_API_SUFFIX = '70cloudflareapikey'

def _md5(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def get_cf_speed_test_ip(timeout=10):
    timestamp = str(int(time.time() * 1000))
    key = _md5(_md5(IP_API_SALT) + IP_API_SUFFIX + timestamp)
    try:
        response = requests.get(
            IP_API_URL,
            params={'key': key, 'time': timestamp},
            headers={'Referer': IP_PAGE_URL, 'User-Agent': 'Mozilla/5.0'},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        group = (payload.get('data') or {}).get(IP_LINE) or {}
        info = group.get('info') or []
        ips = [item['ip'] for item in info if item.get('ip')]
        if ips:
            # 接口已按速度排序，取第一个即为最优 IP
            logger.info("Fetched %d candidate IP(s) for line %s, first: %s", len(ips), IP_LINE, ips[0])
            return ips[:1]
        logger.error("No IP found for line %s in API response: %s", IP_LINE, payload.get('msg'))
    except (requests.RequestException, ValueError, KeyError):
        logger.exception("Failed to fetch candidate IPs")
    return None

def get_dns_records(name):
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records?name={name}'
    try:
        response = requests.get(url, headers=headers, timeout=15)
        data = response.json()
        if response.ok and data.get("success"):
            records = data["result"]
            logger.info("Found %d DNS record(s) for %s", len(records), name)
            return records
        logger.error("Cloudflare DNS query failed for %s: %s", name, data.get("errors", response.text))
    except (requests.RequestException, ValueError):
        logger.exception("Cloudflare DNS query failed for %s", name)
    return []

def update_dns_record(record, ip):
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{record["id"]}'
    data = {
        "type": record["type"],
        "name": record["name"],
        "content": ip,
        "proxied": record.get("proxied", False)
    }
    try:
        response = requests.put(url, headers=headers, json=data, timeout=15)
        result = response.json()
        if response.ok and result.get("success"):
            logger.info("Updated %s from %s to %s", record["name"], record["content"], ip)
            return True
        logger.error("Cloudflare DNS update failed for %s: %s", record["name"], result.get("errors", response.text))
    except (requests.RequestException, ValueError):
        logger.exception("Cloudflare DNS update failed for %s", record["name"])
    return False

def push_plus(content):
    if not PUSHPLUS_TOKEN:
        logger.info("PUSHPLUS_TOKEN is empty; notification skipped")
        return
    url = 'http://www.pushplus.plus/send'
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": "IP优选DNS更新通知",
        "content": content,
        "template": "markdown",
        "channel": "wechat"
    }
    try:
        requests.post(url, json=data, timeout=15).raise_for_status()
    except requests.RequestException:
        logger.exception("PushPlus notification failed")

def main():
    logger.info("DNS update started for: %s", ", ".join(CF_DNS_NAME))
    ip_list = get_cf_speed_test_ip()
    if not ip_list:
        logger.error("No candidate IP was returned; update stopped")
        push_plus("⚠️ 无法获取优选 IP，已停止执行")
        return

    new_ip = ip_list[0]
    result_table = "| 域名 | 原IP | 新IP | 状态 |\n|-----|-----|-----|-----|"

    for domain in CF_DNS_NAME:
        records = get_dns_records(domain)
        if not records:
            result_table += f"\n| {domain} | — | — | ❌ 未找到记录 |"
            continue

        for record in records:
            old_ip = record["content"]

            if old_ip == new_ip:
                result_table += f"\n| {domain} | {old_ip} | {new_ip} | ⏳ 无需更新 |"
            else:
                ok = update_dns_record(record, new_ip)
                result_table += f"\n| {domain} | {old_ip} | {new_ip} | {'✅ 更新成功' if ok else '❌ 更新失败'} |"

            time.sleep(0.8)

    push_plus(result_table)
    logger.info("DNS update finished")

if __name__ == '__main__':
    main()
