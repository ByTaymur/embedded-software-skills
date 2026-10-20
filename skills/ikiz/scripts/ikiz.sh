#!/usr/bin/env bash
# ikiz.sh - Ikiz protokolu icin cocuk Claude Code ajani calistirici (bash/Linux/RPi).
# ikiz.ps1 ile ayni sozlesme. Ayrinti: ../SKILL.md, ../references/komut-sozlugu.md
#
#   ikiz.sh -g gorev.md -o plan-B.json
#   ikiz.sh -g uygula.md -o uygula-B.json -w -W          # yazan cocuk, izole worktree
#   ikiz.sh -G gorevler/ -O sonuclar/ -p 3               # fan-out
set -euo pipefail

GOREV=""; CIKTI=""; GOREV_KLASORU=""; CIKTI_KLASORU=""
MODEL="claude-opus-5"            # cocuk ajan varsayilani opus; tam kimlik sart (alias yok sayilabilir)
ARACLAR="Read,Grep,Glob"
REPO="$PWD"
YAZ=0; WORKTREE=0; PARALEL=2; ZAMAN=900; DAL=""
SISTEM_EKI="Sadece istenen ciktiyi ver, fazladan aciklama yazma. Commit/push/merge yapma. Delege etme, alt ajan baslatma."

kullanim() { sed -n '2,9p' "$0"; exit 1; }

while getopts "g:o:G:O:m:t:r:d:p:T:wWh" opt; do
  case "$opt" in
    g) GOREV="$OPTARG" ;;      o) CIKTI="$OPTARG" ;;
    G) GOREV_KLASORU="$OPTARG" ;; O) CIKTI_KLASORU="$OPTARG" ;;
    m) MODEL="$OPTARG" ;;      t) ARACLAR="$OPTARG" ;;
    r) REPO="$OPTARG" ;;       d) DAL="$OPTARG" ;;
    p) PARALEL="$OPTARG" ;;    T) ZAMAN="$OPTARG" ;;
    w) YAZ=1 ;;                W) WORKTREE=1 ;;
    h|*) kullanim ;;
  esac
done

# --- derinlik kilidi -------------------------------------------------------
if [ "${CLAUDE_IKIZ_DERINLIK:-0}" -ge 1 ] 2>/dev/null; then
  echo "DERINLIK KILIDI: CLAUDE_IKIZ_DERINLIK=$CLAUDE_IKIZ_DERINLIK -- sen zaten cocuk ajansin, delege etme." >&2
  exit 2
fi
export CLAUDE_IKIZ_DERINLIK=1

# --- binary ----------------------------------------------------------------
CLAUDE="$(command -v claude || true)"
[ -z "$CLAUDE" ] && [ -x "$HOME/.local/bin/claude" ] && CLAUDE="$HOME/.local/bin/claude"
if [ -z "$CLAUDE" ]; then echo "claude CLI bulunamadi (PATH veya ~/.local/bin)." >&2; exit 2; fi

# --- worktree --------------------------------------------------------------
CALISMA="$(cd "$REPO" && pwd)"
if [ "$WORKTREE" -eq 1 ]; then
  KOK="$(git -C "$CALISMA" rev-parse --show-toplevel)"
  HEDEF="$(dirname "$KOK")/$(basename "$KOK")-ikiz-B"
  [ -z "$DAL" ] && DAL="ikiz/$(date +%Y%m%d-%H%M)"
  if [ ! -d "$HEDEF" ]; then
    git -C "$KOK" worktree add -b "$DAL" "$HEDEF" >/dev/null || git -C "$KOK" worktree add "$HEDEF" >/dev/null
    echo "[ikiz] worktree hazir: $HEDEF (dal: $DAL)"
  else
    echo "[ikiz] mevcut worktree kullaniliyor: $HEDEF"
  fi
  CALISMA="$HEDEF"
fi

# --- argumanlar ------------------------------------------------------------
if [ "$YAZ" -eq 1 ]; then
  [ "$ARACLAR" = "Read,Grep,Glob" ] && ARACLAR="Read,Grep,Glob,Edit,Write,Bash"
  IZIN=(--permission-mode acceptEdits)
else
  IZIN=()
fi

ARGV=(-p --output-format json --model "$MODEL" --tools "$ARACLAR" "${IZIN[@]}"
      --disallowedTools "Bash(git commit:*),Bash(git push:*),Bash(git merge:*),Bash(git rebase:*)"
      --add-dir "$CALISMA" --append-system-prompt "$SISTEM_EKI")

# --- tek cocuk -------------------------------------------------------------
cocuk_calistir() {
  local gorev="$1" cikti="$2"
  mkdir -p "$(dirname "$cikti")"
  ( cd "$CALISMA" && timeout "${ZAMAN}s" "$CLAUDE" "${ARGV[@]}" < "$gorev" > "$cikti" 2> "${cikti%.json}.err.txt" ) &
  echo $!
}

sonuc_denetle() {
  local cikti="$1" kod="$2"
  if [ "$kod" -eq 124 ]; then echo "zaman-asimi"; return 1; fi
  if [ "$kod" -ne 0 ]; then echo "cikis-kodu=$kod"; return 1; fi
  [ -s "$cikti" ] || { echo "cikti-yok"; return 1; }
  python3 - "$cikti" <<'PY' || { echo "denetim-hatasi"; return 1; }
import json,sys
try: j=json.load(open(sys.argv[1],encoding="utf-8"))
except Exception as e: print("json-ayristirilamadi"); sys.exit(1)
if j.get("is_error"): print("is_error=true"); sys.exit(1)
if not j.get("result"): print("bos-sonuc"); sys.exit(1)
pd=j.get("permission_denials") or []
if pd: print("izin-reddi=%d"%len(pd)); sys.exit(1)
print("ok sure=%sms maliyet=$%s"%(j.get("duration_ms"),j.get("total_cost_usd")))
PY
}

worktree_diff() {
  local out="$1"
  git -C "$CALISMA" add -A -N >/dev/null 2>&1 || true
  git -C "$CALISMA" diff > "$out"
  echo "[ikiz] diff: $out"
  echo "[ikiz] worktree SILINMEDI: $CALISMA  (temizlik: git worktree remove '$CALISMA')"
}

# --- akis ------------------------------------------------------------------
if [ -n "$GOREV" ]; then
  [ -f "$GOREV" ] || { echo "gorev dosyasi yok: $GOREV" >&2; exit 2; }
  [ -z "$CIKTI" ] && CIKTI="${GOREV%.md}.sonuc.json"
  GOREV="$(cd "$(dirname "$GOREV")" && pwd)/$(basename "$GOREV")"
  echo "[ikiz] cocuk basliyor: $GOREV (model=$MODEL, calisma=$CALISMA)"
  pid="$(cocuk_calistir "$GOREV" "$CIKTI")"
  set +e; wait "$pid"; kod=$?; set -e
  [ "$WORKTREE" -eq 1 ] && worktree_diff "${CIKTI%.json}.patch"
  if durum="$(sonuc_denetle "$CIKTI" "$kod")"; then
    echo "[ikiz] TAMAM $durum"
  else
    echo "[ikiz] BASARISIZ ($durum) -> $CIKTI" >&2; exit 1
  fi

elif [ -n "$GOREV_KLASORU" ]; then
  [ -d "$GOREV_KLASORU" ] || { echo "gorev klasoru yok: $GOREV_KLASORU" >&2; exit 2; }
  [ -z "$CIKTI_KLASORU" ] && { echo "-O cikti klasoru gerekli" >&2; exit 2; }
  mkdir -p "$CIKTI_KLASORU"
  hata=0
  for g in "$GOREV_KLASORU"/*.md; do
    [ -e "$g" ] || { echo "gorev klasorunde *.md yok" >&2; exit 2; }
    while [ "$(jobs -rp | wc -l)" -ge "$PARALEL" ]; do sleep 0.4; done
    ad="$(basename "$g" .md)"; out="$CIKTI_KLASORU/$ad.json"
    echo "  -> $ad"
    cocuk_calistir "$(cd "$(dirname "$g")" && pwd)/$(basename "$g")" "$out" >/dev/null
  done
  set +e; wait; set -e
  for g in "$GOREV_KLASORU"/*.md; do
    ad="$(basename "$g" .md)"; out="$CIKTI_KLASORU/$ad.json"
    if durum="$(sonuc_denetle "$out" 0)"; then echo "  OK   $ad  $durum"
    else echo "  HATA $ad  $durum" >&2; hata=1; fi
  done
  exit "$hata"
else
  kullanim
fi
