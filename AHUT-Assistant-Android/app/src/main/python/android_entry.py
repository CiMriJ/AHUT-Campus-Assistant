"""Android 启动入口：由 MainActivity 通过 Chaquopy 调用。"""
import os
import sys


def start(web_dir: str, data_dir: str, port: int = 8765) -> None:
    os.environ["AHUT_WEB_DIR"] = str(web_dir)
    os.environ["AHUT_DATA_DIR"] = str(data_dir)
    sys.argv = ["server.py", "--no-browser", "--host", "127.0.0.1", "--port", str(port)]

    from server import app

    app.run(host="127.0.0.1", port=int(port), threaded=True,
            debug=False, use_reloader=False)
