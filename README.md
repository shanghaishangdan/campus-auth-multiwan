# 校园网认证 + 单线多拨 完全指南（含踩坑手册）

> ⚠️ 仅供学习研究，请遵守所在校园网的使用规范。
>
> 本文档包含**婴儿级手把手教程** + **容易错漏的地方** + **故障排查手册**。那些反直觉的坑，教程里都标了 ⚠️，务必看。

---

## 目录

1. [这是什么](#一这是什么说人话)
2. [你需要准备什么](#二你需要准备什么)
3. [核心概念](#三核心概念1-分钟看懂)
4. [分步教程（婴儿级）](#四分步教程婴儿级手把手)
5. [日常使用](#五日常使用)
6. [⚠️ 容易错漏的地方（必读）](#六️-容易错漏的地方必读)
7. [故障排查手册](#七故障排查手册踩过的坑)
8. [常见问题 FAQ](#八常见问题-faq)
9. [名词速查表](#九名词速查表)
10. [技术细节](#十技术细节进阶)

---

## 一、这是什么？（说人话）

**一句话**：让你的路由器「一根网线同时拨多个号」，把校园网带宽叠加起来，而且**掉线了自动重登录、自动切流量**，不用每天手动点认证。

举个栗子 🌰：

- 宿舍只有**一根网线**，校园网认证后，单账号下载速度比如 **40 Mbps**
- 用这个方案，路由器把这根线「分身」成 2 个（甚至 4 个）虚拟接口，各自认证
- 结果下载速度 **翻倍到 80 Mbps**（因为每个虚拟接口都有独立的带宽配额）

**本方案现在还能做到**（相比普通方案多出来的能力）：

- ✅ 认证掉线后，**流量自动切到另一个口**（不再有「一半流量走死路」）
- ✅ DNS 永不卡（双上游并发 + 分口冗余）
- ✅ 认证服务器静态路由**自动建立**（不依赖部署时机）

---

## 二、你需要准备什么

| 东西 | 说明 |
|------|------|
| **路由器** | 刷了 OpenWrt / iStoreOS 的路由器（mwan3 版本 ≥ 2.10 最佳） |
| **校园网账号** | 1 个（双拨）/ 2 个（四拨），每个账号限 2 台设备 |
| **电脑** | 远程登录路由器（Windows 自带，无需装软件） |
| **网线** | 校园网口到路由器 WAN 口 |

> 不确定路由器是不是 OpenWrt？看登录后台地址是不是 `192.168.1.1` 且界面有「系统」「网络」「服务」菜单，大概率是。

---

## 三、核心概念（1 分钟看懂）

### 1. 什么是「拨号」

校园网插网线后，路由器 WAN 口通过 DHCP 自动拿到 IP（如 `10.0.0.1`），这个过程就是一次拨号。

### 2. 什么是「单线多拨」

通过 **macvlan** 技术，在同一根物理网线上创建多个「虚拟网卡」，每个有独立 MAC 和 IP，等于「一根线拨多个号」。

```
物理网线 eth0
 ├─ eth0mac0（虚拟网卡 1）→ IP 10.112.84.44
 ├─ eth0mac1（虚拟网卡 2）→ IP 10.112.84.48
```

### 3. 什么是「认证」

校园网要先登录认证（输学号密码），认证系统记录「哪个 IP/MAC 已认证」后才放行上网。

### 4. ⚠️ 什么是「半死」（关键概念，务必理解）

这是本方案最核心、最反直觉的一点：

**认证掉线 ≠ 网络断开**。认证掉线时，接口的「物理状态」完全正常：

```
认证掉线（半死）：
  DHCP 租约还在   → 接口有 IP，netifd 认为「在线」
  链路还是亮的    → 网线没断
  ping 还是通的   → ICMP 放行
  DNS 还能解析    → 53 端口放行
  只有 HTTP 被拦  → 访问网页被 302 重定向到认证页
```

所以「认证掉线」这个状态，**只有「HTTP 被 302 拦」这一个信号能暴露它**。mwan3 自带的 ping 检测（测 ICMP）**永远抓不到认证掉线**（因为 ping 通）。

> 这就是为什么后面 mwan3 的 track_ip 要**留空**——因为 ping 检测没用，还帮倒忙。

### 5. 什么是 mwan3

OpenWrt 上的「多 WAN 负载均衡」插件，把上网流量自动分配到多个拨号，让下载速度叠加。

### 6. 什么是 keep 保活

看门狗脚本，每 15 秒检查一次认证状态：发现掉线（HTTP 302）就**切流量 + 重新认证**。

---

## 四、分步教程（婴儿级，手把手）

### 第 0 步：确认你的信息

动手前记下这几个（后面要用）：

1. **路由器登录地址**（一般 `192.168.1.1`）
2. **路由器用户名/密码**（一般 `root` / 你的密码）
3. **校园网账号密码**
4. **认证服务器地址**（从认证页面地址栏抓，如 `10.20.33.101`）

### 第 1 步：登录路由器

Windows 按 `Win + R`，输入 `cmd` 回车：

```sh
ssh root@192.168.1.1
```

> 输密码时屏幕不显示，正常现象。看到 `root@iStoreOS:~#` 就成功了。

### 第 2 步：创建虚拟接口（macvlan）

先看物理 WAN 口叫什么：

```sh
ip link show | grep eth
```

找到连校园网的口（通常 `eth0` 或 `eth1`），假设是 `eth0`：

```sh
ip link add link eth0 eth0mac0 type macvlan mode vepa
ip link add link eth0 eth0mac1 type macvlan mode vepa
```

> **模式必须选 VEPA**，否则多拨认证会出问题。
> 四拨再加 `eth0mac2`、`eth0mac3`。

（也可在 LuCI 网页「网络 → 设备」里点鼠标建，效果一样。）

### 第 3 步：配置逻辑接口

「网络 → 接口」→ 添加新接口：

| 字段 | vwan0 | vwan1 |
|------|-------|-------|
| 名称 | `vwan0` | `vwan1` |
| 协议 | DHCP 客户端 | DHCP 客户端 |
| 设备 | `eth0mac0` | `eth0mac1` |
| 网关跃点 | `10` | `20` |
| 自定义 DNS | `223.5.5.5 223.6.6.6` | 同上 |

> ⚠️ **网关跃点**两个接口要错开（10 / 20）。
> ⚠️ **自定义 DNS** 必须手动填公共 DNS（两个接口填一样的），否则 DHCP 自动分配的 DNS 会打架。

### 第 4 步：配置 mwan3（⚠️ 有几处和网上教程不一样）

浏览器打开 `192.168.1.1` → 「网络 → 负载均衡」，分四层配：

#### ① 接口（Interfaces）—— ⚠️ track_ip 留空！

- 接口名：`vwan0`，绑定接口：`eth0mac0`
- **Track IP：留空（不填！）** ← 这是本方案的关键，网上教程都让你填，别填
- **初始状态（initial_state）：`online`** ← 必须，填 offline 会断网

再建 `vwan1`（绑定 `eth0mac1`），同样留空 track_ip、initial_state 填 online。

> ⚠️ **为什么 track_ip 留空**：认证掉线时 ping 是通的，track_ip 的 ping 检测抓不到掉线，反而会把后面脚本手动切走的接口又拉回 up，导致切流量失效。详见「容易错漏的地方」。

#### ② 成员（Members）

- vwan0：接口选 `vwan0`，跃点数 `1`，权重 `1`
- vwan1：接口选 `vwan1`，跃点数 `1`，权重 `1`

#### ③ 策略（Policies）

- 建 `balanced`：把 vwan0、vwan1 两个成员都加进来

#### ④ 规则（Rules）—— 加一条 DNS 冗余规则

- 默认规则：`0.0.0.0/0 → balanced`（客户端流量负载均衡）
- **新增规则**（放默认规则前面）：
  - 目标端口：`53`
  - 协议：`TCP + UDP`
  - 策略：`balanced`

> 这条是让 DNS 查询也走两个口，防止未来校园网「未认证不放行 DNS」时 DNS 卡死。

### 第 5 步：配置 dnsmasq（DNS 并发）

SSH 执行（用确切的 section 名，别用 `@dnsmasq[0]` 可能不生效）：

```sh
uci set dhcp.@dnsmasq[0].allservers='1'
uci commit dhcp
/etc/init.d/dnsmasq restart
```

> ⚠️ **坑**：`uci set dhcp.@dnsmasq[0]` 有时不生效。先 `uci show dhcp.@dnsmasq[0]` 拿到确切的 section 名（如 `dhcp.cfg01411c`），再用 `uci set dhcp.cfg01411c.allservers='1'`。

### 第 6 步：上传并配置认证脚本

```sh
# 备份旧脚本（如果有）
cp /zy/campus_auth.py /zy/campus_auth.py.bak 2>/dev/null

# 上传（双拨用 2wan，四拨用 4wan）
scp 2wan/campus_auth_openwrt.py root@192.168.1.1:/zy/campus_auth.py
```

编辑配置：

```sh
vi /zy/campus_auth.py
```

改这几处（`vi` 按 `i` 编辑，`Esc` → `:wq` 保存）：

```python
BASE_URL = "http://10.20.33.101/"   # 你的认证服务器地址
INTERFACES = [
    {"name": "vwan0", "iface": "eth0mac0", "user": "学号", "pass": "密码"},
    {"name": "vwan1", "iface": "eth0mac1", "user": "学号", "pass": "密码"},
]
```

> ⚠️ **本脚本已内置静态路由自动建立**（`ensure_static_route`，login 前自动执行），**不再需要手动部署 `99-campus-auth`**。那个 hotplug 脚本有「部署时机」的坑（见故障排查），本脚本已经绕过了。

### 第 7 步：部署保活服务

```sh
scp 2wan/campus_auth.initd root@192.168.1.1:/etc/init.d/campus_auth
chmod +x /etc/init.d/campus_auth
/etc/init.d/campus_auth enable
/etc/init.d/campus_auth start
```

### 第 8 步：装依赖 + 测试

```sh
opkg update && opkg install curl
python3 /zy/campus_auth.py
```

**预期输出**：

```
[vwan0] 成功 - 认证成功！
[vwan1] 成功 - 认证成功！
```

两个都「成功」，双拨认证搞定！测速下载应该翻倍了。

### 第 9 步：验证自动切流量（重要，别跳过）

```sh
# 模拟 vwan0 认证掉线
curl -s --interface eth0mac0 -X POST "http://10.20.33.101/api/logoff.php"

# 立即看 mwan3，balanced 应该只剩 vwan1
mwan3 status

# 等 15 秒，再 status，vwan0 应该自动重认证恢复
python3 /zy/campus_auth.py status
mwan3 status
```

预期：下线瞬间 `balanced = vwan1 (100%)`，15 秒后 `balanced = vwan0 50% + vwan1 50%`。

---

## 五、日常使用

部署完成后**完全不用管**：

- 认证掉线 → keep 15 秒内**切流量 + 自动重认证**
- 重启路由器 → 服务自动启动
- 静态路由 → login 时自动建立（不用手动管）

常用命令：

```sh
python3 /zy/campus_auth.py status    # 查看认证状态
python3 /zy/campus_auth.py logoff    # 手动下线（所有口）
cat /tmp/campus_auth.log             # 查看日志
```

---

## 六、⚠️ 容易错漏的地方（必读）

这一节是所有「反直觉」的坑，每一条都踩过、验证过。

### 坑 1：mwan3 的 track_ip 不要填

**网上教程都让你填 track_ip，本方案必须留空。**

- 认证掉线时 ICMP 放行、ping 通，track_ip 的 ping 检测**永远判「在线」**，抓不到掉线。
- 更糟的是：脚本手动 `mwan3 ifdown` 切流量后，track_ip 的 ping 检测几秒后又把接口拉回 up，**切流量失效**。

### 坑 2：initial_state 必须填 online

不设 track_ip 时（procd 版 mwan3 仍会启动 mwan3track），接口最终状态由 `initial_state` 决定：

- `online` → 接口在线 ✓
- `offline` → 接口**永远离线**，流量走不了 ✗（没有任何检测会把它激活）

### 坑 3：认证掉线是「半死」，mwan3 检测不到

认证掉线时，接口 DHCP 在、链路在、ping 通、DNS 放行，只有 HTTP 被 302 拦。

所以 mwan3 的 **所有** track 检测方式（ping / httping / nping）都抓不到认证掉线：

| 检测方式 | 认证掉线时 | 结果 |
|---------|-----------|------|
| ping（ICMP） | ICMP 放行，通 | 判在线 |
| httping | 收到 302（算「有响应」） | 判在线 |
| nping-tcp | 80 端口开着（返回 302） | 判在线 |

唯一能测认证掉线的是脚本里的 `check_online`（curl generate_204，看 204 还是 302）。

### 坑 4：认证服务器的静态路由必须「分别走各自口」

认证请求靠 `curl --interface eth0mac0` 绑定源接口 + 静态路由锁死各自口。**如果静态路由没建立，认证请求会被 mwan3 分流到错误的口**（带着 A 口的源 IP 从 B 口出去），被校园网 uRPF 丢弃，导致认证失败（`curl rc=7 Failed to connect`）。

本脚本已内置 `ensure_static_route`（login 前自动建立），不用手动管。但如果你用的是旧版 `99-campus-auth` 脚本，注意它的「部署时机」坑（见故障排查 Q6）。

### 坑 5：单线多拨下 metric 切换没用

两个口走**同一根物理网线**（macvlan），物理断线时两个口**一起断**。所以「metric 主备切换」在这个场景下是假命题——切到哪个口都是断的。唯一的冗余是「认证冗余」（一个口认证掉，另一个还认证着）。

### 坑 6：DNS 是命门，要单独做冗余

dnsmasq 转上游 DNS 走 main 表单口，那个口认证掉线（且校园网不放行 DNS）时，DNS 全挂。解法：

1. 配**两个** DNS 上游（223.5.5.5 + 223.6.6.6）
2. dnsmasq 开 `all-servers` 并发
3. mwan3 加 53 端口规则走 balanced

### 坑 7：`grep "prio 50"` 匹配不到

`ip rule show` 的输出是 `50:`（行首数字），不是 `prio 50` 字符串。验证静态路由要用：

```sh
ip rule show | grep "10.20.33.101"   # 用认证服务器 IP 匹配
```

---

## 七、故障排查手册（踩过的坑）

### Q1：认证「重试3次仍失败 - Failed to connect 认证服务器 port 80」

**症状**：`curl rc=7 ... Failed to connect to 10.20.33.101 port 80`

**根因**：认证请求没走静态路由，被 mwan3 分流到错误的口（带着 A 口源 IP 从 B 口出去，被 uRPF 丢弃）。

**排查**：

```sh
ip rule show | grep "10.20.33.101"   # 看 prio 50 静态规则在不在
ip route show table 100             # 看 table 100 有没有认证服务器路由
```

**解决**：手动触发（旧版 99-campus-auth）或直接用新版脚本（login 前自动建）：

```sh
ACTION=ifup DEVICE=eth0mac0 sh /etc/hotplug.d/iface/99-campus-auth
ACTION=ifup DEVICE=eth0mac1 sh /etc/hotplug.d/iface/99-campus-auth
```

### Q2：一个口认证不了，另一个正常

**症状**：status 显示一个口 `logined=1`，另一个口认证失败。

**根因**（通常是两个叠加）：
1. 静态路由没建立（同 Q1）
2. 这个口在 mwan3 里不在 balanced（状态 unknown / offline）

**排查**：

```sh
mwan3 status   # 看 balanced 里有没有这个口
```

**解决**：

```sh
mwan3 ifup <接口名>   # 恢复状态
```

### Q3：mwan3 status 显示接口「unknown」

**原因**：不设 track_ip 时，mwan3track 状态显示 unknown，**这是正常的**，不影响接口参与 balanced。只要 balanced 里有这个口（显示 50%），就没问题。

### Q4：balanced 只剩一个口（另一个不见了）

**原因**：那个口被 `mwan3 ifdown` 了（脚本检测到认证掉线时自动切走），或者手动 ifdown 过。

**解决**：等 keep 重认证成功后自动 ifup 恢复，或手动 `mwan3 ifup <接口名>`。

### Q5：DNS 解析很慢 / 偶尔卡

**原因**：只配了一个 DNS 上游，或者没开 all-servers 并发。

**解决**：配两个上游 + `all-servers` + mwan3 的 53 端口规则。

### Q6：重启后静态路由没建立（旧版 99-campus-auth 的坑）

**原因**：`99-campus-auth` 是 hotplug 脚本，只在接口 `ifup` 事件时触发。如果脚本部署晚于接口 up，就错过了，静态路由不会建立。

**解决**：本方案已把静态路由逻辑搬进认证脚本（`ensure_static_route`），login 前自动建立，不再依赖 hotplug 时机。如果你还在用旧版，部署后手动执行一次（见 Q1）。

### Q7：改了 mwan3 配置不生效

**原因**：mwan3 改完要「保存并应用」，且 `mwan3 restart` 或接口重新 ifup 才生效。

**解决**：LuCI 里改完点「保存并应用」，或命令行 `mwan3 restart`。

---

## 八、常见问题 FAQ

### Q1：下载叠加了，上传没叠加？

**正常现象**。校园网通常**下行按 IP 限速**（可叠加）、**上行按账号限速**（无法叠加）。四拨用 2 个账号才能叠加上行。

### Q2：两个口都认证成功，但网速没翻倍？

检查 mwan3 的 balanced 策略和规则，看流量有没有真正分散到两个口（`mwan3 status` 看 balanced 是不是两个口都在）。

### Q3：重启路由器后失效了？

确认 `campus_auth` 服务已 enable：`/etc/init.d/campus_auth enabled` 应显示 enabled。

### Q4：认证掉线后，普通流量有一半走死路？

这是「半死」导致的——mwan3 检测不到认证掉线，balanced 还把流量分给掉线的口。本方案用 keep 检测 302 + mwan3 ifdown 切流量解决。走死路的窗口 = keep 周期（15 秒）。

### Q5：切流量瞬间客户端闪断一下？

**正常**。`mwan3 ifdown` 会重置走该口的已有连接，客户端重连后走另一个口。

---

## 九、名词速查表

| 名词 | 通俗解释 |
|------|---------|
| OpenWrt / iStoreOS | 开源路由器系统 |
| mwan3 | 多 WAN 负载均衡插件 |
| macvlan | 一根网线创建多个虚拟网卡的技术 |
| DHCP | 自动分配 IP 的协议 |
| 认证 | 校园网登录，认证后放行上网 |
| 半死 | 认证掉线但物理/网络层正常（ping 通、DNS 通，只 HTTP 拦） |
| keep | 保活脚本，掉线切流量 + 重认证 |
| track_ip | mwan3 的检测目标（本方案留空） |
| initial_state | mwan3 接口初始状态（本方案填 online） |
| balanced | mwan3 的负载均衡策略 |
| all-servers | dnsmasq 并发查询所有上游 |
| ip rule | 路由规则，控制流量走哪个出口 |
| uRPF | 反向路径过滤，丢弃源地址错误的包 |

---

## 十、技术细节（进阶）

### 密码加密

- **AES-128-ECB-ZeroPadding**
- 明文 = `4 位随机 salt + 密码`
- 密钥系统级通用，raasportal 已内置 `5a3b9f207411a8ed`

### keep 检测 + 切流量机制

| 状态码 | 含义 | 动作 |
|--------|------|------|
| `204` | 认证在线 | 若之前掉线过，`mwan3 ifup` 切回流量 |
| `302` | 认证掉线 | `mwan3 ifdown` 切走流量 + 重新认证 |
| `err` | 网络抖动 | 跳过 |

### 认证请求的路由（为什么必须静态路由）

认证请求用 `curl --interface eth0mac0` 绑定源 IP，配合 `prio 50` 的静态路由锁死认证服务器走各自口：

```
ip rule: from <vwan0 IP> to <认证服务器> lookup 100 prio 50
table 100: <认证服务器> via <网关> dev eth0mac0
```

`prio 50` 远高于 mwan3 的规则（1000+），所以认证请求永远走自己的口，不被 mwan3 分流。本脚本的 `ensure_static_route` 在 login 前自动建立这套规则，不依赖 hotplug 时机。
