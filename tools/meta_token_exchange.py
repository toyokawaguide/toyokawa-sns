# Meta 短期トークン → 長期トークン(約60日) 変換ツール
# 使い方: PowerShellで  python "C:\Users\Yoshida\Desktop\_meta_token.py"
# 3つ（短期トークン / App ID / App Secret）を1個ずつ貼り付けてEnter
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
import requests

print("=== Meta 長期トークン変換ツール ===")
print("3つを1個ずつ貼り付けてEnterしてください\n")
short = input("(1) 短期トークン を貼り付け: ").strip()
app_id = input("(2) App ID を貼り付け: ").strip()
app_secret = input("(3) App Secret を貼り付け: ").strip()

try:
    r = requests.get(
        "https://graph.facebook.com/v19.0/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short,
        },
        timeout=30,
    )
    j = r.json()
except Exception as e:
    print("\n通信エラー:", e)
    sys.exit(1)

tok = j.get("access_token")
if tok:
    days = round(int(j.get("expires_in", 0)) / 86400) if j.get("expires_in") else "?"
    print("\n==============================")
    print("長期トークン 取得成功！  有効期限: 約", days, "日")
    print("この画面は開いたままにしてください。")
    print("GitHubに貼る直前に、ここで Enter を押すと「コピーし直し」できます。")
    print("（URLやスクショを途中でコピーしても、Enter押せば取り戻せます）")
    print("==============================")
    while True:
        ok = False
        try:
            import subprocess
            subprocess.run("clip", input=tok, text=True, shell=True)
            ok = True
        except Exception:
            ok = False
        if ok:
            print("\n[コピー完了] → GitHubの META_ACCESS_TOKEN の Value欄に Ctrl+V で貼ってください")
        else:
            print("\n[自動コピー失敗] 下を手動でコピー:\n" + tok)
        c = input("もう一度コピー=Enterキー / 終わり=q を入力してEnter : ").strip().lower()
        if c == "q":
            print("お疲れさまでした。")
            break
else:
    print("\n失敗しました。返答:", j)
    print("(短期トークン切れ / 権限不足 / App ID・Secret の誤り などの可能性)")
