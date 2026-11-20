<p align="center">
  <img src="AHUT-Assistant/web/icons/icon-192.png" width="96" alt="AHUT 校园助手图标" />
</p>

<h1 align="center">AHUT 校园助手</h1>

<p align="center">
  安徽工业大学校园信息聚合工具 —— 课表、成绩、考试、通知、校历，一处查看。<br/>
  Windows 本地服务 + 独立 Android App，数据只保存在你自己的设备上。
</p>

---

## 功能特性

**首页概览**
- 本周进度、今日课程数、平均绩点、待考考试统计
- 下一节课提醒、今日课程时间轴
- 考试安排速览、通知公告

**课表**
- 按周切换的全周课表，移动端单日视图
- 课程时间、地点、教师、周次信息
- 自动计算当前教学周（可手动设置学期开始日期与总周数）

**成绩**
- 课程名实时搜索
- 快捷筛选：全部 / 已通过 / 未通过 / 90+
- 平均绩点、学分统计

**考试**
- 考试时间、地点、座位号一览

**更多**
- 通知公告、学年校历
- 学期设置（第一周周一、总周数）
- 个人资料：自定义头像（本地压缩存储）、昵称
- 切换账号 / 退出登录
- 一键导出诊断信息，便于排查问题

**登录方式**
- 学号 + 密码 + 图形验证码（先过 WebVPN，再走学校统一身份认证 CAS，教务系统 SSO 免二次登录）
- 微信扫码登录（学校提供的扫码入口）
- 记住密码时使用 Fernet 本地加密存储，密钥仅保存在本机

**多端**
- 桌面端：浏览器访问，手机连同一 WiFi 也可打开
- Android：内置 Python 运行时，点图标即用，无需电脑、无需 Termux

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.9+、Flask、requests、BeautifulSoup4、lxml |
| 加密/登录 | PyCryptodome（WebVPN AES、教务 RSA）、cryptography（本地凭据 Fernet） |
| 前端 | 原生 HTML / CSS / JavaScript，PWA（manifest + Service Worker） |
| Android | Chaquopy 17.2 + Python 3.11 + WebView + Gradle / AGP 8.7 |

## 目录结构

```
.
├── AHUT-Assistant/                 桌面端（Flask + 原生 Web）
│   ├── ahut/
│   │   ├── config.py               校内地址、WebVPN 链接加密
│   │   ├── vpn.py                  WebVPN 登录与验证码
│   │   ├── jwxt.py                 正方教务：SSO、课表、成绩、考试
│   │   ├── parsers.py              HTML 解析
│   │   ├── campus.py               通知公告、学年校历
│   │   ├── wechat.py               微信扫码登录
│   │   ├── service.py              业务编排、缓存、教学周计算
│   │   └── store.py                本地配置 / Cookie / 缓存 / 密码加密
│   ├── web/                        前端页面（PWA）
│   ├── server.py                   Flask 入口与 API
│   ├── run.bat                     Windows 一键启动
│   ├── termux-setup.sh             Termux 部署脚本（可选）
│   └── requirements.txt
│
└── AHUT-Assistant-Android/         Android 客户端工程（Chaquopy + WebView）
    └── app/src/main/
        ├── java/.../MainActivity.java     WebView、Python 启动、资源释放
        ├── python/                        Python 后端副本 + android_entry.py
        └── assets/web/                    前端资源副本
```

> Android 工程内嵌了一份 `ahut/`、`server.py` 和 `web/` 的副本，以便打包进 APK。
> 修改桌面端代码后，需同步到 `app/src/main/python` 与 `app/src/main/assets/web`，并更新 `assets/web/version.txt`，App 启动时才会重新解压资源。

## 快速开始（桌面端）

**环境要求**：Windows / Linux / macOS，Python 3.9 及以上。

```bash
cd AHUT-Assistant

# 安装依赖
python -m pip install -r requirements.txt

# 启动（默认打开浏览器）
python server.py
```

Windows 用户也可直接双击 `run.bat`，首次运行会自动安装依赖。

启动后：

- 本机访问：`http://127.0.0.1:8765`
- 手机访问：控制台会打印局域网地址（需同一 WiFi，并在防火墙放行）

常用参数：

```bash
python server.py --port 9000          # 指定端口
python server.py --host 127.0.0.1     # 仅本机可访问
python server.py --no-browser         # 不自动打开浏览器
```

> 默认端口被占用时会自动顺延到下一个可用端口。

## Android App

**下载**：到 [Releases](https://github.com/CiMriJ/AHUT-Campus-Assistant/releases) 下载最新 APK。

**安装要求**：Android 7.0（API 24）及以上，arm64 设备（近几年的手机基本都满足）。

安装时如提示"未知来源"，允许即可（应用为自签名）。

**自行构建**：

所需环境：

- JDK 17
- Android SDK：`platforms;android-35`、`build-tools;35.0.0`、`platform-tools`
- Gradle 8.9（或使用 Gradle Wrapper）
- Python 3.11（Chaquopy 构建用，必须与目标版本一致）

```bash
cd AHUT-Assistant-Android
# 在 local.properties 中写入 sdk.dir=你的 Android SDK 路径
# 在 app/build.gradle 中把 buildPython 改成你本机 Python 3.11 的路径

gradle assembleRelease
```

产物：`app/build/outputs/apk/release/app-release.apk`

若使用 Android Studio：直接打开 `AHUT-Assistant-Android` 目录，配置好 SDK 与 `buildPython` 后构建即可。

## 数据与隐私

- Windows：`%LOCALAPPDATA%\AHUT-Assistant`
- Linux / macOS：`~/.ahut-assistant`
- Android：App 私有目录（卸载即清除）

其中保存配置、登录 Cookie、数据缓存与加密后的密码。所有请求均由本机直接发往学校系统，不经过任何第三方服务器。

可通过环境变量覆盖目录（主要用于 Android/自定义部署）：`AHUT_DATA_DIR`、`AHUT_WEB_DIR`。

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/status` | 登录状态、VPN 隧道、已保存账号、学期设置 |
| GET | `/api/captcha?stage=vpn\|jwxt` | 获取对应阶段的图形验证码 |
| POST | `/api/login` | 学号密码登录（含验证码） |
| POST | `/api/qr/start` | 获取微信登录二维码 |
| GET | `/api/qr/poll` | 轮询扫码状态 |
| POST | `/api/logout` | 退出登录（保留用户名） |
| GET | `/api/dashboard?refresh=1` | 仪表盘数据（课表/成绩/考试/通知/校历） |
| POST | `/api/settings` | 保存学期开始日期与总周数 |
| POST | `/api/diag` | 导出诊断信息 |

## 常见问题

**验证码一直提示错误？**
登录需要先通过 WebVPN 验证码，再进入统一身份认证。验证码区分大小写，点击图片可刷新；若反复失败，请确认账号密码可在学校官网正常登录。

**手机打不开桌面端页面？**
确认手机与电脑在同一 WiFi，使用启动时打印的局域网地址，并允许 Windows 防火墙放行 Python。

**Android 首次启动较慢？**
首次启动需要初始化 Python 环境并解压资源，通常几秒到十几秒，之后恢复正常。

**换手机 / 重装后数据没了？**
数据保存在应用私有目录，卸载即清除；桌面端与手机端数据不互通。

**学校系统改版导致数据为空？**
页面结构变化可能需要更新 `ahut/parsers.py` 或 `ahut/jwxt.py` 中的解析逻辑，欢迎提交 Issue。

## 免责声明

本项目为个人学习与技术实践项目，与安徽工业大学官方无关。请遵守学校相关系统使用规定，合理控制请求频率，仅将本项目用于个人查询。因使用本项目产生的一切后果由使用者自行承担。
