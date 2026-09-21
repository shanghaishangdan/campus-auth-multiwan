# 校园网认证 + 单线多拨方案

针对 raasportal 认证系统的校园网，实现**单线多拨（带宽叠加）**、**自动认证**、**掉线保活**。适用于 OpenWrt / iStoreOS 路由器。

> ⚠️ 仅供学习研究，请遵守所在校园网的使用规范。

## 功能特性

- **纯 Python AES 加密**：零第三方依赖，密码加密逻辑内置
- **单线多拨**：双拨 / 四拨，每个拨号接口独立认证、绑定源接口
- **keep 保活**：HTTP `204/302` 精确检测认证状态，掉线自动重连
- **日志自动轮转**：日志超过上限自动截断，不占内存
- **静态路由（99-campus-auth）**：多 WAN 场景防止认证服务器被抢

## 文件结构

| 文件 | 说明 |
|------|------|
| `2wan/` | 双拨版（认证脚本 + 静态路由 + init.d） |
| `4wan/` | 四拨版（需第二个账号） |
| `campus_login.py` | Windows 版（PC 上验证认证逻辑用） |
| `mwan3.user` | mwan3 通知脚本（可选，已由 keep 替代） |
| `verify.bat` | Windows 双击验证脚本 |

## 部署步骤

### 1. 上传主脚本

```sh
scp campus_auth_openwrt.py root@<路由IP>:/zy/campus_auth.py
```

### 2. 配置账号密码

编辑 `/zy/campus_auth.py` 顶部 `INTERFACES`，把 `YOUR_USERNAME` / `YOUR_PASSWORD` 改成真实账号密码。

### 3. 部署 init.d 服务（keep 常驻）

```sh
scp campus_auth.initd root@<路由IP>:/etc/init.d/campus_auth
chmod +x /etc/init.d/campus_auth
/etc/init.d/campus_auth enable
/etc/init.d/campus_auth start
```

### 4. （可选）部署静态路由

仅在**有其他 WAN 抢 default**（如插手机热点）时才需要：

```sh
scp 99-campus-auth root@<路由IP>:/etc/hotplug.d/iface/99-campus-auth
chmod +x /etc/hotplug.d/iface/99-campus-auth
```

### 5. 安装依赖

```sh
opkg update && opkg install curl
```

## 命令用法

```sh
python3 /zy/campus_auth.py              # 认证所有接口
python3 /zy/campus_auth.py login vwan0  # 只认证指定接口
python3 /zy/campus_auth.py logoff       # 下线
python3 /zy/campus_auth.py status       # 查询状态
python3 /zy/campus_auth.py verify       # 验证（认证+连通性）
python3 /zy/campus_auth.py keep         # 保活循环（常驻）
```

## 技术原理

### 密码加密

认证系统的密码加密方式（从前端 `crypto.js` 逆向得到）：

- **AES-128-ECB-ZeroPadding**
- 明文 = `4 位随机 salt + 密码`
- 密钥从认证系统前端 JS 反解（本仓库已脱敏为示例值，需按你的认证系统重新反解）

### keep 检测机制

用 `curl` 访问 `generate_204` 检测认证状态：

| 状态码 | 含义 | 动作 |
|--------|------|------|
| `204` | 认证在线 | 不动作 |
| `302` | 认证掉线（Portal 重定向） | 自动重连 |
| `000`/`err` | 网络抖动 | 跳过，避免误判 |

### 静态路由

多 WAN 场景下，认证服务器（内网）可能被其他 WAN 的 default 路由抢走。`99-campus-auth` 用 `prio 50` 的 ip rule 锁死认证服务器走校园网接口。

## 配置说明

部署前需按你的环境修改：

| 配置项 | 位置 | 说明 |
|--------|------|------|
| 账号密码 | `INTERFACES` | 已脱敏为 `YOUR_USERNAME` / `YOUR_PASSWORD` |
| 认证服务器地址 | `BASE_URL` | 示例值，改成你的 |
| AES 密钥 | `AES_KEY` | 需从你的认证系统前端 JS 反解 |
| 接口名/设备名 | `INTERFACES` 的 `name`/`iface` | 改成你实际的 |
| 网关 | `99-campus-auth` 的 `GW` | 改成你的校园网网关 |

## 双拨 / 四拨

每个账号限 2 台设备：

- **双拨**（`2wan/`）：1 个账号认证 2 个接口（vwan0/vwan1）
- **四拨**（`4wan/`）：2 个账号认证 4 个接口（vwan0~vwan3），把「待填账号2 / 待填密码2」改成真实值

两个文件夹各自包含 3 个脚本（认证脚本 + 99-campus-auth + init.d），按需选择部署。

## 注意事项

- 本方案的 AES 密钥、认证接口因认证系统而异，需自行逆向适配
- 上传公共仓库前务必脱敏账号密码（本仓库已脱敏）
- 多拨能否叠加取决于运营商限速策略（下行通常 IP 级可叠加，上行可能账号级限死）
