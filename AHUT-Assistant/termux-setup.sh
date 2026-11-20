#!/data/data/com.termux/files/usr/bin/bash
# AHUT 校园助手 · Termux 一键安装脚本
# 用法：把项目文件夹传到手机，进入该目录后执行 bash termux-setup.sh

set -e
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "项目目录：$PROJECT_DIR"

echo
echo "==> [1/4] 安装系统依赖（首次会下载较多文件）"
pkg update -y || true
pkg install -y python python-cryptography python-lxml unzip curl

echo
echo "==> [2/4] 安装 Python 依赖"
python -m pip install --upgrade pip
python -m pip install flask requests beautifulsoup4
if ! python -c "import Crypto" >/dev/null 2>&1; then
  pkg install -y python-pycryptodome || {
    echo "未找到 python-pycryptodome，尝试从源码安装"
    pkg install -y clang
    python -m pip install pycryptodome
  }
fi

python - <<'PY'
import flask, requests, bs4, Crypto, cryptography
print("依赖检查通过：Flask", flask.__version__)
PY

echo
echo "==> [3/4] 配置 Termux 开机自启"
BOOT_DIR="$HOME/.termux/boot"
mkdir -p "$BOOT_DIR"
cat > "$BOOT_DIR/ahut-assistant.sh" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock 2>/dev/null || true
cd "$PROJECT_DIR"
if curl -s -m 2 http://127.0.0.1:8765/api/status >/dev/null 2>&1; then
  exit 0
fi
nohup python server.py --no-browser --host 127.0.0.1 --port 8765 >> "\$HOME/ahut-server.log" 2>&1 &
EOF
chmod +x "$BOOT_DIR/ahut-assistant.sh"

echo
echo "==> [4/4] 启动服务"
termux-wake-lock 2>/dev/null || true
if ! curl -s -m 2 http://127.0.0.1:8765/api/status >/dev/null 2>&1; then
  nohup python server.py --no-browser --host 127.0.0.1 --port 8765 >> "$HOME/ahut-server.log" 2>&1 &
  sleep 3
fi

if curl -s -m 3 http://127.0.0.1:8765/api/status >/dev/null 2>&1; then
  echo
  echo "============================================================"
  echo "✅ 服务已启动"
  echo "   请用 Chrome 打开：http://127.0.0.1:8765"
  echo "   再点 Chrome 菜单 →「安装应用 / 添加到主屏幕」"
  echo
  echo "   已配置 Termux:Boot 开机自启；若未安装 Termux:Boot，"
  echo "   可先安装并打开一次（F-Droid 搜索 Termux:Boot）。"
  echo "============================================================"
else
  echo
  echo "❌ 启动失败，请查看日志：tail -n 50 ~/ahut-server.log"
  exit 1
fi
