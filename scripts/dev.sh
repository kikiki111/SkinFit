#!/bin/sh
# 手元で起動し、同じWi-FiのiPhoneから開くURLを表示する。Cloud Runと同じ起動コマンドを使う
cd "$(dirname "$0")/.." || exit 1
PORT="${PORT:-8771}"  # 8080はPickory、8765はfutatakuが使うことがあるため

# 別のアプリがポートを使っていたら、取り違えないように止める
PID="$(lsof -t -iTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -1)"
if [ -n "$PID" ]; then
  echo "ポート ${PORT} は使用中です: $(lsof -nP -p "$PID" 2>/dev/null | awk '$4=="cwd"{print $NF}')"
  echo "別のポートで起動するには: PORT=8772 ./scripts/dev.sh"
  exit 1
fi

IP="$(ipconfig getifaddr en0 2>/dev/null)"
echo "Macで開く:     http://localhost:${PORT}"
[ -n "$IP" ] && echo "iPhoneで開く:  http://${IP}:${PORT}  （同じWi-Fiに接続）"
exec uv run uvicorn app.main:app --host 0.0.0.0 --port "${PORT}"
