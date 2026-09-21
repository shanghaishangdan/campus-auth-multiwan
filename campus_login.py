#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园网认证脚本 (raasportal 系统)
认证入口: http://10.20.33.101/

用法:
    python campus_login.py            # 登录
    python campus_login.py logoff     # 下线
    python campus_login.py status     # 查询在线状态
    python campus_login.py verify     # 验证(登录+测真实连通性)
    python campus_login.py keep       # 保持在线(周期性检测, 掉线自动重连)
"""

import sys
import time
import random
import json
import urllib.request
import urllib.parse

from Crypto.Cipher import AES

# Windows 控制台中文输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ============ 配置 ============
BASE_URL = "http://10.20.33.101/"
USERNAME = "YOUR_USERNAME"
PASSWORD = "YOUR_PASSWORD"
AES_KEY = b"5a3b9f207411a8ed"          # 密钥, 从 crypto.js 反解得到
SALT_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz012345678"  # 前端取前61位

# ============ 密码加密 ============
def encode_password(password: str) -> str:
    """模拟前端 encode(): AES-128-ECB-ZeroPadding 加密 (4位随机salt + 密码), 输出hex"""
    salt = "".join(random.choice(SALT_CHARS) for _ in range(4))
    plain = (salt + password).encode("utf-8")
    # ZeroPadding: 补齐到 16 字节倍数
    pad_len = (16 - len(plain) % 16) % 16
    plain += b"\x00" * pad_len
    cipher = AES.new(AES_KEY, AES.MODE_ECB)
    return cipher.encrypt(plain).hex()


def _post(path: str, data: dict) -> dict:
    url = BASE_URL.rstrip("/") + "/" + path
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("User-Agent", "Mozilla/5.0")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ============ 动作 ============
def login() -> dict:
    """完整登录流程: login -> ack_auth -> stat 确认, 返回最终结果"""
    data = {
        "user": USERNAME,
        "pass": encode_password(PASSWORD),
        "code": "",
        "authmode": "0",
        "pool": "",
        "isp_id": "0",
        "pxyacct": "",
    }

    r = _post("api/login.php", data)
    if r.get("ret"):
        return {"success": False, "msg": r.get("msg", f"登录失败 ret={r.get('ret')}")}

    # 认证确认
    _post("api/ack_auth.php", data)

    # 轮询认证结果 (ret=0 成功; 2/3/4 认证中)
    for _ in range(5):
        s = _post("api/stat.php", data)
        if s.get("ret") == 0:
            return {"success": True, "msg": s.get("msg", "认证成功")}
        if s.get("ret") not in (2, 3, 4):
            return {"success": False, "msg": s.get("msg", f"认证失败 ret={s.get('ret')}")}
        time.sleep(1)

    return {"success": False, "msg": "认证超时"}


def logoff() -> dict:
    return _post("api/logoff.php", {})


def status() -> dict:
    return _post("api/ip.php", {})


def probe_connectivity():
    """测试真实外网连通性: generate_204 返回 204 表示已认证放行"""
    import urllib.error
    try:
        req = urllib.request.Request("http://connect.rom.miui.com/generate_204", method="GET")
        req.add_header("User-Agent", "Mozilla/5.0")
        r = urllib.request.urlopen(req, timeout=6)
        return (r.status == 204), r.status, r.geturl()
    except urllib.error.HTTPError as e:
        return False, e.code, e.geturl()
    except Exception as e:
        return False, None, str(e)


def verify():
    """验证脚本真实有效: 对比登录前后的外网连通性"""
    ok, code, url = probe_connectivity()
    print(f"登录前连通性: {'已放行(在线)' if ok else '未放行(离线)'}  HTTP={code} {url}")
    r = login()
    print(f"登录结果: {'成功' if r['success'] else '失败'} - {r['msg']}")
    time.sleep(2)
    ok2, code2, url2 = probe_connectivity()
    print(f"登录后连通性: {'已放行(在线)' if ok2 else '未放行(离线)'}  HTTP={code2} {url2}")
    if ok2 and not ok:
        print(">>> 验证通过: 脚本成功完成了真实认证")
    elif ok:
        print(">>> 提示: 登录前就已在线, 无法排除假阳性")
    else:
        print(">>> 验证失败: 登录后仍未恢复外网")


def keep_alive(interval: int = 30):
    """周期性检测, 掉线自动重连"""
    print(f"进入保活模式, 每 {interval}s 检测一次, Ctrl+C 退出")
    while True:
        try:
            r = status()
            d = r.get("data", {})
            online = d.get("logined") or d.get("sessionlogined")
            if online:
                print(f"[{time.strftime('%H:%M:%S')}] 在线")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] 离线, 尝试登录...")
                res = login()
                print(f"  结果: {'成功' if res['success'] else '失败'} - {res['msg']}")
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] 检测异常: {e}")
        time.sleep(interval)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "login"

    if action == "login":
        r = login()
        print(f"登录结果: {'成功' if r['success'] else '失败'} - {r['msg']}")
    elif action == "logoff":
        r = logoff()
        print(f"下线: ret={r.get('ret')} msg={r.get('msg')}")
    elif action == "status":
        r = status()
        print(f"状态: {json.dumps(r, ensure_ascii=False)}")
    elif action == "verify":
        verify()
    elif action == "keep":
        keep_alive()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
