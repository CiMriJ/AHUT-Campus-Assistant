"""安徽工业大学校园助手 —— 本地服务入口。

用法：双击 run.bat，或执行  python server.py
浏览器会打开 http://127.0.0.1:8765 ，手机连同一 WiFi 访问控制台打印的局域网地址即可。
"""
import os
import socket
import sys
import threading
import time
import webbrowser

from flask import Flask, Response, jsonify, request, send_from_directory

from ahut import store
from ahut.jwxt import AuthRequired
from ahut.service import Service
from ahut.vpn import VpnError

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Android 版会把 web 资源解压到可写目录，通过 AHUT_WEB_DIR 指定
WEB_DIR = os.environ.get("AHUT_WEB_DIR") or os.path.join(BASE_DIR, "web")

app = Flask(__name__, static_folder=None)
service = Service()


# ---------------- 静态页面 ----------------

@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEB_DIR, filename)


# ---------------- 接口 ----------------

@app.get("/api/status")
def api_status():
    try:
        vpn_ready = service.vpn.probe_tunnel(max_age=120)
    except Exception:
        vpn_ready = False
    return jsonify({
        "logged_in": service.is_logged_in(),
        "vpn_ready": vpn_ready,
        "username": service.saved_username(),
        "password_saved": bool(service.saved_password()),
        "term_start": service.cfg.get("term_start", ""),
        "total_weeks": service.cfg.get("total_weeks", 20),
        "has_data": bool(service.cached()),
    })


@app.get("/api/captcha")
def api_captcha():
    stage = request.args.get("stage", "vpn")
    try:
        img = service.captcha(stage)
    except VpnError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    return Response(img, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/qr/start")
def api_qr_start():
    try:
        return jsonify(service.qr_start())
    except Exception as exc:
        return jsonify({"ok": False, "error": f"二维码获取失败：{exc}"}), 200


@app.get("/api/qr/poll")
def api_qr_poll():
    try:
        return jsonify(service.qr_poll())
    except Exception as exc:
        return jsonify({"state": "error", "error": f"扫码状态查询失败：{exc}"}), 200


@app.post("/api/login")
def api_login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    captcha = (body.get("captcha") or "").strip()
    jwxt_password = body.get("jwxt_password") or ""
    jwxt_captcha = body.get("jwxt_captcha") or ""
    remember = bool(body.get("remember"))
    if not username or not password:
        return jsonify({"ok": False, "error": "请输入学号和密码"}), 400
    try:
        result = service.login(username, password, captcha, jwxt_password, remember, jwxt_captcha)
    except VpnError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 200
    except Exception as exc:  # 兜底，避免前端只看到 500
        return jsonify({"ok": False, "error": f"登录异常：{exc}"}), 200
    return jsonify(result)


@app.post("/api/logout")
def api_logout():
    service.logout()
    return jsonify({"ok": True})


@app.get("/api/dashboard")
def api_dashboard():
    force = request.args.get("refresh") == "1"
    try:
        return jsonify(service.dashboard(force=force))
    except VpnError as exc:
        return jsonify({"logged_in": False, "need_login": True, "error": str(exc)})
    except Exception as exc:
        return jsonify({"logged_in": False, "need_login": True, "error": f"数据获取失败：{exc}"})


@app.post("/api/settings")
def api_settings():
    body = request.get_json(silent=True) or {}
    if "term_start" in body:
        raw = (body.get("term_start") or "").strip()
        if raw:
            try:
                time.strptime(raw, "%Y-%m-%d")
            except ValueError:
                return jsonify({"ok": False, "error": "日期格式应为 YYYY-MM-DD"}), 400
        service.cfg["term_start"] = raw
    if "total_weeks" in body:
        try:
            service.cfg["total_weeks"] = max(1, min(30, int(body["total_weeks"])))
        except (TypeError, ValueError):
            pass
    store.save_config(service.cfg)
    return jsonify({"ok": True, "term_start": service.cfg.get("term_start", ""),
                    "total_weeks": service.cfg.get("total_weeks", 20)})


@app.post("/api/diag")
def api_diag():
    if not service.is_logged_in():
        return jsonify({"ok": False, "error": "请先登录后再导出"}), 400
    try:
        return jsonify({"ok": True, **service.export_diag()})
    except AuthRequired as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------- 启动 ----------------

def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _pick_port(start: int = 8765) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start


def main():
    port = 8765
    if "--port" in sys.argv:
        try:
            port = int(sys.argv[sys.argv.index("--port") + 1])
        except (ValueError, IndexError):
            port = 8765
    else:
        port = _pick_port(port)

    host = "0.0.0.0"
    if "--host" in sys.argv:
        try:
            host = sys.argv[sys.argv.index("--host") + 1]
        except IndexError:
            host = "0.0.0.0"

    url = f"http://127.0.0.1:{port}"
    lan = f"http://{_lan_ip()}:{port}"
    print("=" * 56)
    print("  安徽工业大学 校园助手")
    print(f"  本机访问：{url}")
    if host == "0.0.0.0":
        print(f"  手机访问：{lan}   （需同一 WiFi）")
    print(f"  数据目录：{store.DATA_DIR}")
    print("=" * 56)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
