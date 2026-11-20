"""正方教务系统（jsxsd）客户端：登录与数据抓取。"""
import base64
import re
from typing import Any
from urllib.parse import quote

import requests
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

from . import config as C
from . import parsers
from .vpn import VpnClient, VpnError


class AuthRequired(VpnError):
    """会话失效，需要重新登录。"""


class JwxtClient:
    def __init__(self, vpn: VpnClient):
        self.vpn = vpn
        self.s = vpn.s
        self.base = C.JWXT_VPN
        self.logged_in = False
        self._captcha_src = ""

    # ---------- 基础请求 ----------

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return self.base.rstrip("/") + "/" + path.lstrip("/")

    def get(self, path: str, **kw) -> requests.Response:
        kw.setdefault("timeout", 25)
        kw.setdefault("verify", False)
        r = self.s.get(self._url(path), **kw)
        if _is_login_page(r.text):
            raise AuthRequired("教务系统登录状态已失效")
        return r

    def post(self, path: str, data: dict, **kw) -> requests.Response:
        kw.setdefault("timeout", 25)
        kw.setdefault("verify", False)
        r = self.s.post(self._url(path), data=data, **kw)
        if _is_login_page(r.text):
            raise AuthRequired("教务系统登录状态已失效")
        return r

    # ---------- 登录 ----------

    def open_login_page(self) -> str:
        r = self.s.get(self.base, timeout=25, verify=False)
        html = r.text
        self._captcha_src = ""
        for img in re.findall(r'<img[^>]+src="([^"]*(?:kaptcha|captcha|validate)[^"]*)"', html, re.I):
            self._captcha_src = img
            break
        return html

    def captcha_image(self) -> bytes:
        if not self._captcha_src:
            self.open_login_page()
        if not self._captcha_src:
            raise VpnError("教务系统未提供验证码")
        url = self._captcha_src
        if url.startswith("/jsxsd"):
            url = C.WEBVPN_BASE + "/http/" + C.vpn_host_hex(C.JWXT_HOST) + url
        r = self.s.get(url, timeout=15, verify=False)
        return r.content

    def login_via_sso(self) -> dict[str, Any]:
        """通过统一身份认证（CAS）票据登录教务系统，无需教务系统独立密码。

        CAS 会话仍然有效时，会直接返回带 ticket 的跳转，教务系统随即建立登录态。
        返回 need_cas_login=True 表示需要重新做一次统一身份认证（带验证码）。
        """
        service = "http://jwxt.ahut.edu.cn/jsxsd/sso.jsp"
        cas_login = (
            f"{C.WEBVPN_BASE}/https/{C.vpn_host_hex(C.CAS_HOST)}/cas/login"
            f"?service={quote(service, safe='')}"
        )
        try:
            r = self.s.get(cas_login, timeout=25, verify=False, allow_redirects=False)
        except requests.RequestException as exc:
            return {"ok": False, "error": f"统一身份认证不可达：{exc}"}

        if r.status_code not in (301, 302, 303, 307, 308):
            return {"ok": False, "need_cas_login": True,
                    "error": "统一身份认证登录状态已过期"}

        ticket_url = r.headers.get("Location", "")
        if "ticket=" not in ticket_url:
            return {"ok": False, "need_cas_login": True, "error": "未获取到统一认证票据"}

        # VPN 会把跳转地址重写为隧道路径；若是真实域名则手动改写
        for host in ("http://jwxt.ahut.edu.cn", "https://jwxt.ahut.edu.cn"):
            if ticket_url.startswith(host):
                ticket_url = self.base.rstrip("/") + ticket_url[len(host):]
                break
        if ticket_url.startswith("/"):
            ticket_url = C.WEBVPN_BASE + ticket_url

        try:
            r2 = self.s.get(ticket_url, timeout=25, verify=False, allow_redirects=True)
        except requests.RequestException as exc:
            return {"ok": False, "error": f"教务系统票据校验失败：{exc}"}

        if _is_login_page(r2.text):
            return {"ok": False, "error": "教务系统未接受统一认证票据",
                    "need_cas_login": True}
        self.logged_in = True
        return {"ok": True, "error": ""}

    def login(self, username: str, password: str, captcha: str = "") -> dict[str, Any]:
        html = self.open_login_page()
        if not _is_login_page(html):
            self.logged_in = True
            return {"ok": True, "error": ""}

        if "LoginToXk" in html:
            # 安工大版本：encoded = base64(账号) + "%%%" + base64(密码)，密码明文不再提交
            data = {
                "userAccount": username,
                "userPassword": "",
                "encoded": _encode_inp(username) + "%%%" + _encode_inp(password),
                "pwdstr1": "",
                "pwdstr2": "",
            }
            action = "xk/LoginToXk"
        else:
            modulus = _grab(html, r'id="modulus"[^>]*value="([0-9a-fA-F]+)"') \
                or _grab(html, r'var\s+modulus\s*=\s*"([0-9a-fA-F]+)"')
            exponent = _grab(html, r'id="exponent"[^>]*value="([0-9a-fA-F]+)"') or "10001"
            enc_password = password
            if modulus:
                try:
                    key = RSA.construct((int(modulus, 16), int(exponent, 16)))
                    enc_password = PKCS1_v1_5.new(key).encrypt(password.encode()).hex()
                except Exception:
                    enc_password = password
            data = {"userAccount": username, "userPassword": enc_password}
            if captcha:
                data["RANDOMCODE"] = captcha
            action = "Logon.do?method=logon"

        r = self.s.post(self._url(action), data=data, timeout=25,
                        verify=False, allow_redirects=True)
        text = r.text

        if _is_login_page(text):
            hint = _login_error(text)
            need_captcha = bool(re.search(r'<input[^>]+name="RANDOMCODE"[^>]*>', text))
            return {"ok": False, "error": hint or "教务系统登录失败", "captcha": need_captcha}

        probe = self.s.get(self.base, timeout=20, verify=False)
        if _is_login_page(probe.text):
            return {"ok": False, "error": _login_error(probe.text) or "教务系统登录失败（账号或密码错误）"}
        self.logged_in = True
        return {"ok": True, "error": ""}

    # ---------- 数据抓取 ----------

    def timetable_html(self) -> str:
        return self.get(C.JWXT_PATHS["timetable"]).text

    def grades_html(self) -> str:
        self.get(C.JWXT_PATHS["grades"])  # 先建立会话与查询条件
        r = self.post(C.JWXT_PATHS["grades"], {
            "kksj": "", "kcxz": "", "kcmc": "", "xsfs": "all",
        })
        return r.text

    def exams_html(self) -> str:
        return self.get(C.JWXT_PATHS["exams"]).text

    def classroom_html(self, week: str = "", weekday: str = "", period: str = "") -> str:
        r = self.get(C.JWXT_PATHS["classroom"], params={
            "xnxq01id": "", "zc": week, "xqid": "", "jslx": "",
        })
        return r.text


def _grab(html: str, pattern: str) -> str:
    m = re.search(pattern, html or "", re.I)
    return m.group(1) if m else ""


def _encode_inp(text: str) -> str:
    """对齐正方页面里的 encodeInp（标准 Base64，ASCII 下与 JS 实现一致）。"""
    return base64.b64encode(text.encode("utf-8")).decode()


def _login_error(html: str) -> str:
    """从正方登录页提取错误提示（优先匹配已知文案）。"""
    for kw in ("用户名或密码错误", "密码错误", "验证码错误", "验证码不正确",
               "用户不存在", "账号被锁定", "该账号已锁定"):
        if kw in (html or ""):
            return kw
    for m in re.finditer(r'<li[^>]*color:\s*red[^>]*>(.*?)</li>', html or "", re.S | re.I):
        txt = re.sub(r"<[^>]+>|&nbsp;|\s+", " ", m.group(1)).strip()
        if txt and "温馨提示" not in txt and "浏览器" not in txt:
            return txt
    return ""


def _is_login_page(html: str) -> bool:
    if not html:
        return False
    return ('id="userAccount"' in html or 'name="userAccount"' in html) and \
           ('id="userPassword"' in html or 'name="userPassword"' in html)


def fetch_all(client: JwxtClient) -> dict[str, Any]:
    """抓取并解析全部教务数据。单个模块失败不影响其他模块。"""
    result: dict[str, Any] = {"errors": {}}

    for key, fn, parser in (
        ("timetable", client.timetable_html, parsers.parse_timetable),
        ("grades", client.grades_html, parsers.parse_grades),
        ("exams", client.exams_html, parsers.parse_exams),
    ):
        try:
            result[key] = parser(fn())
        except AuthRequired:
            raise
        except Exception as exc:
            result[key] = {"adapted": False}
            result["errors"][key] = str(exc)

    try:
        # 学籍页在安工大版本会提示“非法访问”，学号从课表页里取更稳
        result["student"] = parsers.parse_student(client.timetable_html())
    except Exception:
        result["student"] = {}
    return result
