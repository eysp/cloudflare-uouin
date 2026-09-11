import requests
import traceback
import hashlib
import time
import os
import json

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

# 获取优选 IP
# cloudflare.html 的表格是 2024 年的静态快照，真实数据由页面 ajax 拉取
IP_PAGE_URL = 'https://api.uouin.com/cloudflare.html'
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
        if response.status_code == 200:
            group = (response.json().get('data') or {}).get(IP_LINE) or {}
            ips = [item['ip'] for item in (group.get('info') or []) if item.get('ip')]
            return ips[:1]
    except:
        traceback.print_exc()
    return None

# 获取 DNS 记录
def get_dns_records(name):
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records?name={name}'
    response = requests.get(url, headers=headers)
    data = response.json()
    if response.ok and data.get("success"):
        return data["result"]
    print(f'Cloudflare DNS query failed: {data.get("errors", response.text)}')
    return []

# 更新 DNS 记录
def update_dns_record(record, ip):
    url = f'https://api.cloudflare.com/client/v4/zones/{CF_ZONE_ID}/dns_records/{record["id"]}'
    data = {
        "type": record["type"],
        "name": record["name"],
        "content": ip,
        "proxied": record.get("proxied", False)
    }
    response = requests.put(url, headers=headers, json=data)
    result = response.json()
    if response.ok and result.get("success"):
        return True
    print(f'Cloudflare DNS update failed: {result.get("errors", response.text)}')
    return False

# 推送
def push_plus(content):
    url = 'http://www.pushplus.plus/send'
    data = {
        "token": PUSHPLUS_TOKEN,
        "title": "IP优选DNS更新通知",
        "content": content,
        "template": "markdown",
        "channel": "wechat"
    }
    requests.post(url, json=data)

def main():
    ip_list = get_cf_speed_test_ip()
    if not ip_list:
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

            # 不变则跳过更新
            if old_ip == new_ip:
                result_table += f"\n| {domain} | {old_ip} | {new_ip} | ⏳ 无需更新 |"
            else:
                ok = update_dns_record(record, new_ip)
                if ok:
                    result_table += f"\n| {domain} | {old_ip} | {new_ip} | ✅ 更新成功 |"
                else:
                    result_table += f"\n| {domain} | {old_ip} | {new_ip} | ❌ 更新失败 |"

            time.sleep(0.8)  # 防 API 封锁

    push_plus(result_table)

if __name__ == '__main__':
    main()
