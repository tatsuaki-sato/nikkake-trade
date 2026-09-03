#!/usr/bin/env bash
# 動作確認用スモークテスト。
# 事前に開発サーバーを起動しておくこと:
#   docker compose -f docker-compose.dev.yml up --build
# 使い方:
#   scripts/smoke_test.sh [BASE_URL]   # 既定 http://localhost:8000
set -u
BASE="${1:-http://localhost:8000}"
fail=0

check() { # 名前 期待コード URL [追加curl引数...]
  local name="$1" want="$2" url="$3"; shift 3
  local got
  got="$(curl -s -o /dev/null -w '%{http_code}' "$@" "$url")"
  if [ "$got" = "$want" ]; then
    printf 'PASS  %-40s %s\n' "$name" "$got"
  else
    printf 'FAIL  %-40s got=%s want=%s\n' "$name" "$got" "$want"
    fail=1
  fi
}

# 各画面が固有URLを持つ
loc="$(curl -s -o /dev/null -w '%{redirect_url}' "$BASE/")"
if [ "$loc" = "$BASE/candidates" ] || [ "$loc" = "/candidates" ]; then
  printf 'PASS  %-40s %s\n' "GET / redirects to /candidates" "$loc"
else
  printf 'FAIL  %-40s got=%s\n' "GET / redirects to /candidates" "$loc"; fail=1
fi

check "GET /candidates -> 200"         200 "$BASE/candidates"
check "GET /portfolio  -> 200"         200 "$BASE/portfolio"
check "GET /api/history -> 200"        200 "$BASE/api/history"
check "GET /api/portfolio -> 200"      200 "$BASE/api/portfolio"
check "GET /unknown -> 404"            404 "$BASE/unknown-path"

# 生成HTMLが壊れていない（scriptタグが閉じている / ルーティングJSが入っている）
html="$(curl -s "$BASE/candidates")"
o="$(printf '%s' "$html" | grep -c '<script')"
c="$(printf '%s' "$html" | grep -oE '</script>' | wc -l | tr -d ' ')"
if [ "$o" = "$c" ]; then
  printf 'PASS  %-40s open=%s close=%s\n' "script tags balanced" "$o" "$c"
else
  printf 'FAIL  %-40s open=%s close=%s\n' "script tags balanced" "$o" "$c"; fail=1
fi
if printf '%s' "$html" | grep -q 'initTabRouting'; then
  printf 'PASS  %-40s\n' "tab-routing JS present"
else
  printf 'FAIL  %-40s\n' "tab-routing JS present"; fail=1
fi

[ "$fail" = 0 ] && echo && echo "ALL GREEN" || { echo; echo "FAILURES"; exit 1; }
