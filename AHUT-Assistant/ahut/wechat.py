"""微信扫码登录：走学校统一身份认证的联合登录（openweixin）。"""
import base64
import re
import time
from urllib.parse import parse_qs, quote, urlencode, urlparse

import requests

from . import config as C


class WechatQr:
    """一次扫码登录的完整状态：二维码 uuid、state、CAS 回调地址。"""

    def __init__(self, session: requests.Session):
        self.s = session
        self.uuid = ""
        self.state = ""
        self.redirect_uri = ""
        self.created = 0.0

    def start(self) -> dict:
        url = (f"{C.CAS_BASE}/cas/federatedRedirect"
               f"?service={quote(C.JWXT_SSO_SERVICE, safe='')}&federatedName=openweixin")
        try:
            r = self.s.get(url, timeout=25, verify=False)
        except requests.RequestException as exc:
            return {"ok": False, "error": f"统一认证不可达：{exc}"}

        m = re.search(r"l/qrconnect\?uuid=([0-9A-Za-z_-]+)", r.text or "")
        if not m:
            return {"ok": False, "error": "未获取到微信二维码，请改用账号密码登录"}
        self.uuid = m.group(1)

        q = parse_qs(urlparse(r.url).query)
        self.state = (q.get("state") or [""])[0]
        self.redirect_uri = (q.get("redirect_uri") or [""])[0]
        if not self.redirect_uri:
            return {"ok": False, "error": "统一认证未返回回调地址"}
        self.created = time.time()

        try:
            qr = self.s.get(f"https://open.weixin.qq.com/connect/qrcode/{self.uuid}",
                            timeout=20, verify=False)
        except requests.RequestException as exc:
            return {"ok": False, "error": f"二维码加载失败：{exc}"}
        if qr.status_code != 200 or not qr.content:
            return {"ok": False, "error": "二维码加载失败"}

        mime = (qr.headers.get("Content-Type") or "image/png").split(";")[0]
        return {
            "ok": True,
            "image": f"data:{mime};base64," + base64.b64encode(qr.content).decode(),
            "expires_in": 300,
        }

    def poll(self, timeout: int = 25) -> dict:
        if not self.uuid or time.time() - self.created > 300:
            return {"state": "expired"}
        try:
            r = self.s.get("https://long.open.weixin.qq.com/connect/l/qrconnect",
                           params={"uuid": self.uuid}, timeout=timeout + 10, verify=False)
        except requests.RequestException:
            return {"state": "waiting"}

        m = re.search(r"wx_errcode\s*=\s*(\d+)", r.text or "")
        if not m:
            return {"state": "waiting"}
        err = int(m.group(1))
        if err == 405:
            code = re.search(r"wx_code\s*=\s*'([^']*)'", r.text or "")
            return {"state": "confirmed", "code": code.group(1) if code else ""}
        if err == 404:
            return {"state": "scanned"}
        if err == 402:
            return {"state": "expired"}
        return {"state": "waiting"}

    def finish(self, wx_code: str) -> dict:
        """扫码确认后用 code 完成 CAS 回调，并顺带换好 WebVPN 隧道票据。"""
        sep = "&" if "?" in self.redirect_uri else "?"
        callback = self.redirect_uri + sep + urlencode({"code": wx_code, "state": self.state})
        try:
            r = self.s.get(callback, timeout=25, verify=False, allow_redirects=False)
        except requests.RequestException as exc:
            return {"ok": False, "error": f"统一认证回调失败：{exc}"}

        # 先用同一个统一认证会话把 WebVPN 隧道票据换到手，否则隧道路径进不去
        try:
            self.s.get(C.WEBVPN_BASE + "/", timeout=25, verify=False, allow_redirects=True)
        except requests.RequestException:
            pass

        for _ in range(4):
            loc = r.headers.get("Location", "")
            if not loc:
                break
            if loc.startswith("/"):
                loc = C.CAS_BASE + loc
            if "jwxt.ahut.edu.cn" in loc:
                tail = loc.split("jwxt.ahut.edu.cn", 1)[1]
                target = f"{C.WEBVPN_BASE}/http/{C.vpn_host_hex(C.JWXT_HOST)}{tail}"
            else:
                target = loc
            try:
                r = self.s.get(target, timeout=25, verify=False, allow_redirects=False)
            except requests.RequestException as exc:
                return {"ok": False, "error": f"教务系统回调失败：{exc}"}
            if "jwxt.ahut.edu.cn" in loc:
                break
        return {"ok": True, "error": ""}
