"""WebVPN + 统一身份认证（CAS）登录。

校外访问教务系统的链路：
    本机 -> vpncas.ahut.edu.cn（深信服 WebVPN，登录走 CAS 统一身份认证）
         -> 隧道 /http/<加密域名>/jsxsd/... -> 正方教务系统
"""
import re

import requests
import urllib3

from . import config as C

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_INVALID_CODE_HINT = ("验证码", "captcha")
_ERROR_HINTS = (
    "用户名或者密码", "密码错误", "账号或密码", "用户名或密码",
    "验证码", "已被锁定", "账号不存在", "用户不存在", "登录失败",
)


class VpnError(Exception):
    """登录或隧道访问异常。"""


def _clean(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "")


class VpnClient:
    def __init__(self, session: requests.Session | None = None):
        self.s = session or requests.Session()
        self.s.headers.update({
            "User-Agent": C.USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        self.s.verify = False
        self._execution = ""
        self.logged_in = False
        self._probe_ok = False
        self._probe_ts = 0.0

    # ---------- 基础请求 ----------

    def _get(self, url, **kw):
        kw.setdefault("timeout", 20)
        kw.setdefault("allow_redirects", True)
        return self.s.get(url, **kw)

    def _post(self, url, data, **kw):
        kw.setdefault("timeout", 25)
        kw.setdefault("allow_redirects", True)
        return self.s.post(url, data=data, **kw)

    # ---------- 登录页 / 验证码 ----------

    def open_login_page(self) -> str:
        """打开 VPN 登录页（内部跳转 CAS），返回页面 HTML。"""
        try:
            r = self._get(C.WEBVPN_BASE + "/")
        except requests.RequestException as exc:
            raise VpnError(f"无法连接学校 WebVPN 服务器：{exc}") from exc
        html = r.text
        m = re.search(r'name="execution"\s+value="([^"]+)"', html)
        if not m:
            m = re.search(r'name=execution\s+value=([^\s>]+)', html)
        self._execution = m.group(1) if m else ""
        return html

    def captcha_image(self) -> bytes:
        """取统一身份认证的图片验证码。"""
        urls = [
            f"{C.WEBVPN_BASE}/https/{C.vpn_host_hex(C.CAS_HOST)}/cas/captcha.jpg",
            f"{C.WEBVPN_BASE}/captcha.jpg",
            f"{C.WEBVPN_BASE}/https/{C.vpn_host_hex(C.CAS_HOST)}/cas/captcha",
        ]
        for url in urls:
            try:
                r = self.s.get(url, timeout=15, verify=False)
            except requests.RequestException:
                continue
            ctype = r.headers.get("Content-Type", "")
            if r.status_code == 200 and ("image" in ctype or r.content[:2] == b"\xff\xd8"):
                return r.content
        raise VpnError("获取验证码失败，请点击刷新重试")

    # ---------- 提交登录 ----------

    @staticmethod
    def _page_error(html: str) -> str:
        text = _clean(html)
        for hint in _ERROR_HINTS:
            idx = text.find(hint)
            if idx >= 0:
                snippet = re.sub(r"\s+", " ", text[max(0, idx - 40): idx + 40]).strip()
                return snippet
        return ""

    def submit_login(self, username: str, password: str, captcha: str) -> dict:
        """提交 CAS 登录表单，返回 {ok, error}。"""
        if not self._execution:
            self.open_login_page()

        data = {
            "username": username,
            "password": password,
            "captcha": captcha,
            "mfaState": "",
            "currentMenu": "1",
            "failN": "-1",
            "execution": self._execution,
            "_eventId": "submit",
            "geolocation": "",
            "fpVisitorId": "",
            "submit": "Login1",
        }
        endpoints = [
            C.WEBVPN_BASE + "/login",
            f"{C.WEBVPN_BASE}/https/{C.vpn_host_hex(C.CAS_HOST)}/cas/login",
        ]
        last_html = ""
        for url in endpoints:
            try:
                r = self._post(url, data)
            except requests.RequestException as exc:
                return {"ok": False, "error": f"提交登录请求失败：{exc}"}
            last_html = r.text
            if self.probe_tunnel():
                self.logged_in = True
                return {"ok": True, "error": ""}

        # 登录失败，尽量提取原因
        err = self._page_error(last_html)
        if err and any(k in err for k in _INVALID_CODE_HINT):
            return {"ok": False, "error": "验证码不正确或已过期，请重新输入", "captcha": True}
        if err:
            return {"ok": False, "error": f"登录失败：{err}", "captcha": True}
        return {
            "ok": False,
            "error": "登录失败，请检查学号/密码，或刷新验证码后重试",
            "captcha": True,
        }

    # ---------- 连通性探测 ----------

    def probe_tunnel(self, max_age: float = 0) -> bool:
        """用教务系统地址探测隧道是否已放行（未被踢回登录页即视为成功）。

        max_age > 0 时复用最近一次成功的探测结果，避免每次打开页面都请求学校。
        """
        import time
        if self._probe_ok and max_age and time.time() - self._probe_ts < max_age:
            return True
        try:
            r = self.s.get(C.JWXT_VPN, timeout=12, allow_redirects=False, verify=False)
        except requests.RequestException:
            return False
        ok = True
        if r.status_code in (301, 302, 303, 307, 308):
            loc = r.headers.get("Location", "")
            if "/login" in loc:
                ok = False
        else:
            ok = r.status_code == 200
        self._probe_ok = ok
        self._probe_ts = time.time()
        return ok

    def restore(self) -> bool:
        """用本地 Cookie 恢复登录态。"""
        ok = self.probe_tunnel()
        self.logged_in = ok
        return ok
