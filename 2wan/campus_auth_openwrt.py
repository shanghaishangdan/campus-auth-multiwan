#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校园网认证脚本 (raasportal) —— OpenWrt 单线双拨 / mwan3 版
零第三方依赖 (纯 Python AES + curl), 每个拨号接口独立认证、绑定源接口。

依赖: curl (OpenWrt 需 opkg install curl)

用法:
    python3 campus_auth_openwrt.py                 # 认证所有接口
    python3 campus_auth_openwrt.py login <name>    # 只认证指定接口(按配置里的 name)
    python3 campus_auth_openwrt.py logoff          # 下线
    python3 campus_auth_openwrt.py status          # 查询状态
    python3 campus_auth_openwrt.py verify          # 认证并对比前后连通性
    python3 campus_auth_openwrt.py keep            # 保活循环(所有接口)
"""

import sys
import time
import json
import os
import random
import subprocess
import urllib.parse
import re

# 行缓冲输出, 确保 procd 常驻时日志实时刷到 logread
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# ==================== 配置区 ====================
BASE_URL = "http://YOUR_AUTH_SERVER/"
AES_KEY = b"5a3b9f207411a8ed"           # 密钥, 从 crypto.js 反解得到
CHECK_URL = "http://connect.rom.miui.com/generate_204"  # 在线检测目标(204 即已放行)
SALT_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz012345678"

# 单线双拨: 每个拨号接口一条配置
#   name: mwan3 逻辑接口名(对应热插拔 $INTERFACE)
#   iface: 物理设备名(对应 $DEVICE, curl --interface 绑定它, 保证从该拨号出去)
#   user / pass: 该接口的认证账号密码
INTERFACES = [
    {"name": "vwan0", "iface": "eth0mac0", "user": "YOUR_USERNAME", "pass": "YOUR_PASSWORD"},
    {"name": "vwan1", "iface": "eth0mac1", "user": "YOUR_USERNAME", "pass": "YOUR_PASSWORD"},
]

# 日志轮转: 超过上限时只保留最后 N 行
LOG_FILE = "/tmp/campus_auth.log"
LOG_MAX_BYTES = 512 * 1024   # 512KB 触发轮转
LOG_KEEP_LINES = 200         # 轮转后保留最后 200 行

# ==================== 纯 Python AES-128 ====================
SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
]
RCON = [0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36]


def _xtime(a):
    return (((a << 1) ^ 0x1b) & 0xff) if (a & 0x80) else ((a << 1) & 0xff)


def _key_expansion(key16):
    w = [0] * 44
    for i in range(4):
        w[i] = (key16[4*i] << 24) | (key16[4*i+1] << 16) | (key16[4*i+2] << 8) | key16[4*i+3]
    for i in range(4, 44):
        t = w[i-1]
        if i % 4 == 0:
            t = ((t << 8) | (t >> 24)) & 0xffffffff
            t = (SBOX[(t >> 24) & 0xff] << 24) | (SBOX[(t >> 16) & 0xff] << 16) | \
                (SBOX[(t >> 8) & 0xff] << 8) | SBOX[t & 0xff]
            t ^= RCON[i // 4] << 24
        w[i] = w[i-4] ^ t
    return w


def _shift_rows(s):
    return [s[0], s[5], s[10], s[15],
            s[4], s[9], s[14], s[3],
            s[8], s[13], s[2], s[7],
            s[12], s[1], s[6], s[11]]


def _mix_columns(s):
    for c in range(4):
        a0, a1, a2, a3 = s[4*c], s[4*c+1], s[4*c+2], s[4*c+3]
        s[4*c]   = _xtime(a0) ^ _xtime(a1) ^ a1 ^ a2 ^ a3
        s[4*c+1] = a0 ^ _xtime(a1) ^ _xtime(a2) ^ a2 ^ a3
        s[4*c+2] = a0 ^ a1 ^ _xtime(a2) ^ _xtime(a3) ^ a3
        s[4*c+3] = _xtime(a0) ^ a0 ^ a1 ^ a2 ^ _xtime(a3)
    return s


def aes_ecb_encrypt(data, key):
    """AES-128-ECB 加密, data 长度需为 16 的倍数"""
    w = _key_expansion(key)
    out = bytearray()
    for off in range(0, len(data), 16):
        s = list(data[off:off+16])
        for c in range(4):
            for r in range(4):
                s[4*c+r] ^= (w[c] >> (24 - 8*r)) & 0xff
        for rnd in range(1, 10):
            s = [SBOX[b] for b in s]
            s = _shift_rows(s)
            s = _mix_columns(s)
            for c in range(4):
                for r in range(4):
                    s[4*c+r] ^= (w[rnd*4+c] >> (24 - 8*r)) & 0xff
        s = [SBOX[b] for b in s]
        s = _shift_rows(s)
        for c in range(4):
            for r in range(4):
                s[4*c+r] ^= (w[40+c] >> (24 - 8*r)) & 0xff
        out += bytes(s)
    return bytes(out)


def encode_password(password):
    """模拟前端 encode(): AES-ECB-ZeroPadding(4位随机salt + 密码) -> hex"""
    salt = "".join(random.choice(SALT_CHARS) for _ in range(4))
    plain = (salt + password).encode("utf-8")
    plain += b"\x00" * ((16 - len(plain) % 16) % 16)
    return aes_ecb_encrypt(plain, AES_KEY).hex()


# ==================== HTTP (curl 绑定源接口) ====================
def curl_post(iface, path, data):
    """通过指定接口发 POST, 返回 JSON dict; 空返回/异常自动重试 3 次"""
    url = BASE_URL.rstrip("/") + "/" + path
    body = urllib.parse.urlencode(data).encode("utf-8")
    cmd = ["curl", "-sS", "--interface", iface, "-X", "POST",
           "--data-binary", body, "--max-time", "10", url]
    last_err = ""
    for attempt in range(3):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=15)
            out = r.stdout.decode("utf-8", errors="replace").strip()
            if out:
                return json.loads(out)
            last_err = "curl rc=%s err=%s" % (r.returncode,
                                              r.stderr.decode("utf-8", errors="replace").strip())
        except Exception as e:
            last_err = str(e)
        time.sleep(1)
    return {"ret": -1, "msg": "重试3次仍失败: %s" % last_err}


# ==================== 动作 ====================
def find(name):
    for cfg in INTERFACES:
        if cfg["name"] == name:
            return cfg
    return None


def ensure_static_route(cfg):
    """login 前确保认证服务器走本接口的静态路由, 避免依赖 hotplug 时机"""
    iface = cfg["iface"]
    auth_ip = urllib.parse.urlparse(BASE_URL).hostname
    if not auth_ip:
        return
    r = subprocess.run(["ip", "-4", "addr", "show", iface],
                       capture_output=True, text=True)
    m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)/', r.stdout)
    if not m:
        return
    ip = m.group(1)
    r = subprocess.run(["ip", "route", "show", "dev", iface],
                       capture_output=True, text=True)
    m = re.search(r'default via (\d+\.\d+\.\d+\.\d+)', r.stdout)
    if not m:
        return
    gw = m.group(1)
    tbl = 100 + INTERFACES.index(cfg)
    subprocess.run(["ip", "route", "replace", auth_ip + "/32", "via", gw,
                    "dev", iface, "table", str(tbl)], capture_output=True)
    subprocess.run(["ip", "rule", "del", "from", ip, "to", auth_ip,
                    "lookup", str(tbl), "prio", "50"], capture_output=True)
    subprocess.run(["ip", "rule", "add", "from", ip, "to", auth_ip,
                    "lookup", str(tbl), "prio", "50"], capture_output=True)


def login(cfg):
    """认证单个接口: login -> ack_auth -> stat 确认"""
    ensure_static_route(cfg)
    data = {
        "user": cfg["user"], "pass": encode_password(cfg["pass"]), "code": "",
        "authmode": "0", "pool": "", "isp_id": "0", "pxyacct": "",
    }
    r = curl_post(cfg["iface"], "api/login.php", data)
    if r.get("ret"):
        return {"success": False, "msg": r.get("msg", "登录失败 ret=%s" % r.get("ret"))}
    curl_post(cfg["iface"], "api/ack_auth.php", data)
    for _ in range(5):
        s = curl_post(cfg["iface"], "api/stat.php", data)
        if s.get("ret") == 0:
            return {"success": True, "msg": s.get("msg", "认证成功")}
        if s.get("ret") not in (2, 3, 4):
            return {"success": False, "msg": s.get("msg", "认证失败 ret=%s" % s.get("ret"))}
        time.sleep(1)
    return {"success": False, "msg": "认证超时"}


def login_all():
    for cfg in INTERFACES:
        r = login(cfg)
        print("[%s] %s - %s" % (cfg["name"], "成功" if r["success"] else "失败", r["msg"]))


def check_online(iface):
    """通过指定接口检测认证状态, 返回 (在线, http_code); 重试3次避免偶发误判"""
    code = "err"
    for _ in range(3):
        try:
            cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                   "--interface", iface, "--max-time", "6", CHECK_URL]
            r = subprocess.run(cmd, capture_output=True, timeout=12)
            code = r.stdout.decode(errors="replace").strip() or "err"
            if code == "204":
                return True, code
        except Exception:
            code = "err"
        time.sleep(1)
    return False, code


def _trim_log():
    """日志超过上限时, 只保留最后 LOG_KEEP_LINES 行"""
    try:
        if not os.path.exists(LOG_FILE):
            return
        if os.path.getsize(LOG_FILE) <= LOG_MAX_BYTES:
            return
        with open(LOG_FILE, "r", errors="ignore") as f:
            lines = f.readlines()
        with open(LOG_FILE, "w") as f:
            f.writelines(lines[-LOG_KEEP_LINES:])
    except Exception:
        pass


def keep(interval=15):
    """保活: 遍历所有接口, 掉线则切流量(mwan3 ifdown)并重认证"""
    print("双拨保活启动, 每 %ds 检测一次" % interval)
    n = 0
    prev = {cfg["name"]: True for cfg in INTERFACES}
    while True:
        try:
            for cfg in INTERFACES:
                name = cfg["name"]
                ok, code = check_online(cfg["iface"])
                if ok:
                    if not prev.get(name, True):
                        subprocess.run(["mwan3", "ifup", name], capture_output=True)
                        print("[%s %s] 恢复在线, 流量切回" % (time.strftime("%H:%M:%S"), name))
                    prev[name] = True
                elif code == "302":
                    if prev.get(name, True):
                        subprocess.run(["mwan3", "ifdown", name], capture_output=True)
                        print("[%s %s] 认证掉线(http=302), 流量切走" % (time.strftime("%H:%M:%S"), name))
                    prev[name] = False
                    r = login(cfg)
                    print("  结果: %s - %s" % ("成功" if r["success"] else "失败", r["msg"]))
                else:
                    print("[%s %s] 检测失败(http=%s), 跳过" % (time.strftime("%H:%M:%S"), name, code))
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print("[%s] 异常: %s" % (time.strftime("%H:%M:%S"), e))
        n += 1
        if n % 100 == 0:   # 每 100 轮检查一次日志大小
            _trim_log()
        time.sleep(interval)


def verify():
    for cfg in INTERFACES:
        before, _ = check_online(cfg["iface"])
        print("[%s] 登录前: %s" % (cfg["name"], "在线" if before else "离线"))
        r = login(cfg)
        print("[%s] 登录: %s - %s" % (cfg["name"], "成功" if r["success"] else "失败", r["msg"]))
        time.sleep(2)
        after, _ = check_online(cfg["iface"])
        print("[%s] 登录后: %s" % (cfg["name"], "在线" if after else "离线"))


def main():
    args = sys.argv[1:]
    action = args[0] if args else "login-all"

    if action == "login-all":
        login_all()
    elif action == "login":
        name = args[1] if len(args) > 1 else ""
        cfg = find(name)
        if not cfg:
            sys.exit(0)  # 静默: mwan3.user 会传入各种接口, 非本脚本管理的接口直接跳过
        r = login(cfg)
        print("[%s] 登录结果: %s - %s" % (cfg["name"], "成功" if r["success"] else "失败", r["msg"]))
    elif action == "logoff":
        for cfg in INTERFACES:
            r = curl_post(cfg["iface"], "api/logoff.php", {})
            print("[%s] 下线: ret=%s" % (cfg["name"], r.get("ret")))
    elif action == "status":
        for cfg in INTERFACES:
            r = curl_post(cfg["iface"], "api/ip.php", {})
            print("[%s] %s" % (cfg["name"], json.dumps(r, ensure_ascii=False)))
    elif action == "verify":
        verify()
    elif action == "keep":
        keep()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
