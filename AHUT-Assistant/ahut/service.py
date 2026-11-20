"""业务编排：登录状态、数据抓取、缓存、周次计算、诊断导出。"""
import datetime as dt
import json
import threading
import time
from typing import Any

import requests

from . import campus, config as C, jwxt, store, wechat
from .vpn import VpnClient, VpnError

CACHE_TTL = 300  # 秒


class Service:
    def __init__(self):
        self.cfg = store.load_config()
        self.lock = threading.RLock()
        self.vpn = VpnClient()
        self._restore_cookies()
        self.jwxt = jwxt.JwxtClient(self.vpn)
        self.qr = wechat.WechatQr(self.vpn.s)
        self.qr_lock = threading.Lock()
        self.data: dict[str, Any] = {}
        self.data_ts = 0
        cached, ts = store.load_cache()
        if cached:
            self.data, self.data_ts = cached, ts
        self.vpn.logged_in = False

    # ---------- 会话 ----------

    def _restore_cookies(self):
        cookies = store.load_cookies()
        if not cookies:
            return
        for c in cookies:
            try:
                self.vpn.s.cookies.set(
                    c.get("name", ""), c.get("value", ""),
                    domain=c.get("domain", ""), path=c.get("path", "/"),
                )
            except Exception:
                continue

    def _save_cookies(self):
        try:
            store.save_cookies(self.vpn.s.cookies)
        except Exception:
            pass

    def is_logged_in(self) -> bool:
        return bool(self.jwxt.logged_in or self.data)

    # ---------- 登录流程 ----------

    def prepare_login(self) -> dict:
        html = self.vpn.open_login_page()
        return {"ok": True, "has_captcha": "captcha" in html}

    def captcha(self, stage: str = "vpn") -> bytes:
        with self.lock:
            if stage == "jwxt" and self.vpn.probe_tunnel(max_age=60):
                try:
                    return self.jwxt.captcha_image()
                except VpnError:
                    pass
            return self.vpn.captcha_image()

    def login(self, username: str, password: str, captcha_code: str,
              jwxt_password: str = "", remember: bool = False,
              jwxt_captcha: str = "") -> dict:
        with self.lock:
            # 1) 先打通 WebVPN 隧道（走统一身份认证，需要图片验证码）
            if not self.vpn.probe_tunnel(max_age=60):
                res = self.vpn.submit_login(username, password, captcha_code)
                if not res.get("ok"):
                    res["stage"] = "vpn"
                    return res
                self._save_cookies()

            # 2) 优先用统一身份认证票据登录教务系统，不需要教务系统独立密码
            sso = self.jwxt.login_via_sso()
            if not sso.get("ok") and sso.get("need_cas_login"):
                if not captcha_code:
                    return {
                        "ok": False,
                        "stage": "vpn",
                        "need_captcha": True,
                        "error": "智慧校园登录状态已过期，请输入验证码后重新登录",
                    }
                res = self.vpn.submit_login(username, password, captcha_code)
                if not res.get("ok"):
                    res["stage"] = "vpn"
                    return res
                self._save_cookies()
                sso = self.jwxt.login_via_sso()

            if sso.get("ok"):
                return self._finish_login(username, password, remember)

            # 3) 统一认证票据不可用时，退回教务系统账号密码
            pwd2 = jwxt_password or password
            jres = self.jwxt.login(username, pwd2, jwxt_captcha)
            if jres.get("ok"):
                return self._finish_login(username, password, remember)

            msg = jres.get("error") or sso.get("error") or "教务系统登录失败"
            hint = ""
            if "密码" in msg or "账号" in msg or "用户名" in msg:
                hint = "如果教务系统密码与智慧校园密码不同，请展开「教务系统密码不同」单独填写。"
            return {
                "ok": False,
                "stage": "jwxt",
                "error": f"已连上学校 VPN，但教务系统登录失败：{msg}。{hint}",
                "need_jwxt_password": True,
                "captcha": bool(jres.get("captcha")),
            }

    # ---------- 微信扫码登录 ----------

    def qr_start(self) -> dict:
        with self.qr_lock:
            return self.qr.start()

    def qr_poll(self, timeout: int = 25) -> dict:
        with self.qr_lock:
            st = self.qr.poll(timeout)
            if st.get("state") != "confirmed":
                return st
            fin = self.qr.finish(st.get("code", ""))
            if not fin.get("ok"):
                return {"state": "error", "error": fin.get("error", "扫码登录失败")}

        sso = self.jwxt.login_via_sso()
        if not sso.get("ok"):
            return {"state": "error", "error": sso.get("error") or "教务系统登录失败"}
        with self.lock:
            self.jwxt.logged_in = True
            self._save_cookies()
            self.data, self.data_ts = {}, 0
        return {"state": "ok"}

    def _finish_login(self, username: str, password: str, remember: bool) -> dict:
        self.cfg["username"] = username
        self.cfg["remember_password"] = bool(remember)
        self.cfg["password_enc"] = store.encrypt_password(password) if remember else ""
        store.save_config(self.cfg)
        self._save_cookies()
        self.data, self.data_ts = {}, 0
        return {"ok": True, "error": ""}

    def logout(self):
        with self.lock:
            self.vpn.s.cookies.clear()
            store.clear_cookies()
            self.jwxt.logged_in = False
            self.vpn.logged_in = False
            self.data, self.data_ts = {}, 0
            store.save_cache({})

    def saved_username(self) -> str:
        return self.cfg.get("username", "")

    def saved_password(self) -> str:
        if self.cfg.get("remember_password"):
            return store.decrypt_password(self.cfg.get("password_enc", ""))
        return ""

    # ---------- 数据 ----------

    def refresh(self, force: bool = False) -> dict:
        with self.lock:
            if not force and self.data and time.time() - self.data_ts < CACHE_TTL:
                return self.data
            try:
                data = jwxt.fetch_all(self.jwxt)
            except jwxt.AuthRequired:
                # 教务登录态过期时，先用统一认证票据静默恢复，再重试一次
                if not self.jwxt.login_via_sso().get("ok"):
                    raise
                data = jwxt.fetch_all(self.jwxt)
            data["notices"] = _safe(campus.notices)
            data["calendar"] = _safe(campus.calendar)
            data["fetched_at"] = int(time.time())
            self.data, self.data_ts = data, time.time()
            store.save_cache(data)
            self._save_cookies()
            return data

    def cached(self) -> dict:
        return self.data or {}

    # ---------- 周次 ----------

    def term_start(self) -> dt.date | None:
        raw = (self.cfg.get("term_start") or "").strip()
        if raw:
            try:
                return dt.date.fromisoformat(raw)
            except ValueError:
                return None
        return self._default_term_start()

    @staticmethod
    def _default_term_start() -> dt.date:
        """未设置时按学期规律估算第一周周一（秋季 8 月底、春季 2 月中）。"""
        today = dt.date.today()
        if today.month >= 8:
            base = dt.date(today.year, 8, 25)
        elif today.month <= 1:
            base = dt.date(today.year - 1, 8, 25)
        else:
            base = dt.date(today.year, 2, 18)
        return base + dt.timedelta(days=(7 - base.weekday()) % 7)

    def current_week(self) -> dict:
        start = self.term_start()
        monday = start - dt.timedelta(days=start.weekday())
        today = dt.date.today()
        week = (today - monday).days // 7 + 1
        return {
            "current": max(1, min(week, 30)),
            "total": int(self.cfg.get("total_weeks") or 20),
            "start": monday.isoformat(),
            "estimated": not bool((self.cfg.get("term_start") or "").strip()),
        }

    # ---------- 汇总 ----------

    def dashboard(self, force: bool = False) -> dict:
        data = self.cached()
        error = ""
        try:
            data = self.refresh(force=force)
        except jwxt.AuthRequired:
            return {"logged_in": False, "need_login": True}
        except (VpnError, requests.RequestException) as exc:
            error = str(exc)
            if not data:
                return {"logged_in": False, "need_login": True, "error": error}

        week = self.current_week()
        today_idx = dt.date.today().isoweekday()
        timetable = data.get("timetable", {}) or {}
        courses = timetable.get("courses", []) or []

        today_courses = [c for c in courses
                         if c.get("weekday") == today_idx
                         and (not c.get("weeks") or week["current"] in c["weeks"])]
        today_courses.sort(key=lambda c: c.get("period") or 0)

        all_exams = (data.get("exams", {}) or {}).get("items", []) or []

        return {
            "logged_in": True,
            "student": data.get("student", {}) or {},
            "week": week,
            "today": {"weekday": today_idx, "courses": today_courses},
            "timetable": timetable,
            "grades": data.get("grades", {}) or {},
            "grade_summary": _grade_summary(data.get("grades", {}) or {}),
            "exams": all_exams,
            "notices": data.get("notices", []) or [],
            "calendar": data.get("calendar", {}) or {},
            "errors": data.get("errors", {}) or {},
            "fetched_at": data.get("fetched_at", 0),
            "error": error,
            "periods": [{"label": a, "start": b, "end": c} for a, b, c in C.PERIOD_TIMES],
        }

    # ---------- 诊断 ----------

    def export_diag(self) -> dict:
        out = store.DEBUG_DIR
        out.mkdir(parents=True, exist_ok=True)
        files = []
        pages = {}
        try:
            pages["timetable.html"] = self.jwxt.timetable_html()
        except Exception as exc:
            pages["timetable.error.txt"] = str(exc)
        try:
            pages["grades.html"] = self.jwxt.grades_html()
        except Exception as exc:
            pages["grades.error.txt"] = str(exc)
        try:
            pages["exams.html"] = self.jwxt.exams_html()
        except Exception as exc:
            pages["exams.error.txt"] = str(exc)
        try:
            pages["jwxt_home.html"] = self.jwxt.open_login_page()
        except Exception as exc:
            pages["jwxt_home.error.txt"] = str(exc)

        for name, content in pages.items():
            p = out / name
            p.write_text(content, encoding="utf-8", errors="ignore")
            files.append(str(p))

        meta = out / "status.json"
        meta.write_text(json.dumps({
            "time": dt.datetime.now().isoformat(),
            "logged_in": self.is_logged_in(),
            "config": {k: v for k, v in self.cfg.items() if k != "password_enc"},
            "data_keys": list((self.data or {}).keys()),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        files.append(str(meta))
        return {"dir": str(out), "files": files}


def _safe(fn):
    try:
        return fn()
    except Exception as exc:
        return {"error": str(exc), "items": []}


def _grade_summary(grades: dict) -> dict:
    items = grades.get("items", []) or []
    credits = 0.0
    score_sum = 0.0
    point_sum = 0.0
    point_credit = 0.0
    failed = 0
    for it in items:
        credit = it.get("credit") or 0
        score = it.get("score") or ""
        import re
        m = re.search(r"-?\d+(\.\d+)?", str(score))
        if not m:
            continue
        val = float(m.group(0))
        credits += credit
        score_sum += val * credit
        if val < 60:
            failed += 1
        point = it.get("point")
        if point is not None:
            point_sum += point * credit
            point_credit += credit
    return {
        "count": len(items),
        "credits": round(credits, 1),
        "weighted": round(score_sum / credits, 2) if credits else None,
        "gpa": round(point_sum / point_credit, 3) if point_credit else None,
        "failed": failed,
    }
