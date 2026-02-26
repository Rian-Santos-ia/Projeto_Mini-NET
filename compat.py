# compat.py
# Compatibilidade de caracteres especiais entre sistemas operacionais.
# No Windows (cp1252), substitui símbolos Unicode por equivalentes ASCII.

import sys

if sys.platform == "win32":
    # Força UTF-8 no stdout do Windows
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    try:
        # Windows 10+: ativa modo UTF-8 no terminal
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Símbolos usados nos logs — fallback ASCII para terminais limitados
def safe(simbolo, fallback):
    try:
        simbolo.encode(sys.stdout.encoding or 'utf-8')
        return simbolo
    except (UnicodeEncodeError, LookupError):
        return fallback

CHECK    = safe("✓",  "OK")
CHECKDBL = safe("✓✓", "OK")
CROSS    = safe("✗",  "X")
CLOCK    = safe("🕐", "...")
RELOAD   = safe("🔄", ">>")
GREEN    = safe("🟢", "[+]")
RED      = safe("🔴", "[-]")
