from __future__ import annotations

import re

GOLD_MT5_SYMBOL = "XAUUSDm"
GOLD_TV_SYMBOL = "XAUUSD"
GOLD_TV_EXCHANGE = "OANDA"

A_SHARE_DEFAULT_SYMBOL = "000001"
A_SHARE_DEFAULT_TIMEFRAME = "1h"

TV_GOLD_SYMBOL_BY_EXCHANGE: dict[str, str] = {
    "OANDA": "XAUUSD",
    "PEPPERSTONE": "XAUUSD",
    "FOREXCOM": "XAUUSD",
    "FX": "XAUUSD",
    "FXCM": "XAUUSD",
    "TVC": "GOLD",
    "CAPITALCOM": "GOLD",
}

_CRYPTO_HINTS = ("BTC", "ETH", "USDT", "SOL", "DOGE", "BNB", "XRP", "CRYPTO")

TV_CRYPTO_EXCHANGES: tuple[str, ...] = (
    "BINANCE",
    "BITSTAMP",
    "COINBASE",
    "BYBIT",
    "OKX",
    "BITFINEX",
    "HUOBI",
)

_CRYPTO_SYMBOL_EXCHANGE_HINTS: dict[str, str] = {
    "BTCUSDT": "BINANCE",
    "ETHUSDT": "BINANCE",
    "BTCUSD": "BITSTAMP",
    "ETHUSD": "BITSTAMP",
    "SOLUSDT": "BINANCE",
    "BNBUSDT": "BINANCE",
    "XRPUSDT": "BINANCE",
    "DOGEUSDT": "BINANCE",
}

_KNOWN_INDEX_TICKERS: dict[str, list[tuple[str, str]]] = {
    "SPX": [("SP", "SPX"), ("NYSE", "SPX"), ("CBOT", "SPX"), ("TVC", "SPX")],
    "NDX": [("NASDAQ", "NDX"), ("TVC", "NDX")],
    "DJI": [("DJ", "DJI"), ("NYSE", "DJI"), ("TVC", "DJI")],
    "VIX": [("CBOT", "VIX"), ("CBOE", "VIX"), ("TVC", "VIX")],
    "ES1!": [("CME_MINI", "ES1!"), ("CME", "ES1!")],
    "NQ1!": [("CME_MINI", "NQ1!"), ("CME", "NQ1!")],
    "YM1!": [("CBOT", "YM1!"), ("CME", "YM1!")],
    "RUT": [("NYSE", "RUT"), ("TVC", "RUT")],
}

TV_ASHARE_EXCHANGES: frozenset[str] = frozenset({"SSE", "SZSE"})
TV_HK_EXCHANGE = "HKEX"
TV_HK_EXCHANGES: frozenset[str] = frozenset({TV_HK_EXCHANGE, "HK", "HKG", "HONGKONG"})
TV_EQUITY_EXCHANGES: frozenset[str] = TV_ASHARE_EXCHANGES | TV_HK_EXCHANGES
TV_SSE_INDEX_CODES: frozenset[str] = frozenset(
    {"000016", "000300", "000905", "000852"}
)

# Forex / spot gold and China A-share (tvDatafeed exchange ids)
TV_EXCHANGE_PRESETS: tuple[str, ...] = (
    "OANDA",
    "PEPPERSTONE",
    "FOREXCOM",
    "FX",
    "TVC",
    "CAPITALCOM",
    "SSE",
    "SZSE",
    "HKEX",
    "SP",
    "NYSE",
    "NASDAQ",
    "CBOT",
    "CME_MINI",
    "",
)

_STOCK_CODE_RE = re.compile(r"^\d{6}$")
_INDEX_PREFIX_RE = re.compile(r"^(sh|sz)(\d{6})$", re.IGNORECASE)


def _is_index_digits(digits: str) -> bool:
    return digits in {
        "000300", "000016", "000905", "000852",
        "399001", "399006", "399300",
    }


def normalize_ashare_symbol(symbol: str) -> str:
    raw = (symbol or "").strip()
    if not raw:
        return ""
    m = _INDEX_PREFIX_RE.match(raw)
    if m:
        prefix, digits = m.group(1).lower(), m.group(2)
        if _is_index_digits(digits):
            return f"{prefix}{digits}"
        return digits
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 6:
        return digits[-6:]
    return digits


def _looks_like_ashare_code(code: str) -> bool:
    c = (code or "").strip().lower()
    if len(c) == 6 and c.isdigit():
        return True
    return c.startswith(("sh", "sz")) and len(c) >= 8 and c[2:].isdigit()


def is_likely_crypto_symbol(symbol: str) -> bool:
    s = (symbol or "").upper().replace("/", "").replace("-", "")
    return any(h in s for h in _CRYPTO_HINTS)


def normalize_gold_symbol_for_kind(kind: str, symbol: str) -> str:
    sym = (symbol or "").strip()
    if kind == "akshare":
        code = normalize_ashare_symbol(sym)
        if not code or not _looks_like_ashare_code(code):
            return A_SHARE_DEFAULT_SYMBOL
        return code
    if kind == "tradingview":
        code = normalize_ashare_tv_code(sym)
        if _is_ashare_tv_code(code):
            return code
        hk = normalize_hk_tv_code(sym)
        if _is_hk_tv_code(hk):
            return hk
    if not sym or is_likely_crypto_symbol(sym):
        return GOLD_TV_SYMBOL if kind == "tradingview" else GOLD_MT5_SYMBOL
    if kind == "tradingview" and sym.lower().endswith("m") and len(sym) > 2:
        return GOLD_TV_SYMBOL
    return sym


def normalize_gold_tv_exchange(exchange: str) -> str:
    ex = (exchange or "").strip().upper()
    if is_tv_exchange_auto(ex):
        return ""
    if ex in ("BINANCE", "COINBASE", "BITSTAMP", "BYBIT", "OKX", "KRAKEN"):
        return ""
    return ex


def normalize_ashare_tv_code(symbol: str) -> str:
    raw = normalize_ashare_symbol(symbol)
    if raw.startswith(("sh", "sz")) and len(raw) >= 8:
        return raw[2:8]
    digits = re.sub(r"\D", "", raw)
    if len(digits) >= 6:
        return digits[-6:]
    return digits


def _is_ashare_tv_code(code: str) -> bool:
    return len(code) == 6 and code.isdigit()


def normalize_hk_tv_code(symbol: str) -> str:
    return re.sub(r"\D", "", (symbol or "").strip())


def _is_hk_tv_code(code: str) -> bool:
    return bool(code) and code.isdigit() and 1 <= len(code) <= 5


def is_partial_tv_symbol_input(symbol: str) -> bool:
    from data.tradingview.symbol_lookup import is_tv_name_input

    s = (symbol or "").strip()
    if not s:
        return True
    if is_tv_name_input(s):
        key = re.sub(r"\s+", "", s)
        return len(key) < 2
    if s.isdigit():
        if len(s) < 3:
            return True
        if len(s) == 6:
            return False
        if 3 <= len(s) <= 5:
            return False
    return False


def is_numeric_tv_equity_symbol(symbol: str) -> bool:
    s = (symbol or "").strip()
    return bool(s) and s.isdigit()


def infer_ashare_tv_exchange(code: str) -> str:
    if code.startswith(("688", "689")):
        return "SSE"
    if code in TV_SSE_INDEX_CODES or code.startswith(
        ("5", "600", "601", "603", "605", "900")
    ):
        return "SSE"
    if code.startswith(("399", "300", "301", "002", "003", "001")):
        return "SZSE"
    if code.startswith("000"):
        return "SZSE"
    return "SSE"


def is_tv_exchange_auto(exchange: str) -> bool:
    ex = (exchange or "").strip().upper()
    return ex in ("", "AUTO")


_GOLD_TV_SYMBOLS = frozenset({"XAUUSD", "GOLD", "XAU"})


def tv_forex_auto_probe_plan(symbol: str) -> list[tuple[str, str]]:
    sym = (symbol or "").strip().upper() or GOLD_TV_SYMBOL
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ex in TV_EXCHANGE_PRESETS:
        if not ex or ex in TV_EQUITY_EXCHANGES or ex in TV_CRYPTO_EXCHANGES:
            continue
        if sym in _GOLD_TV_SYMBOLS:
            feed = TV_GOLD_SYMBOL_BY_EXCHANGE.get(ex)
            if feed is None:
                continue
            pair = (ex, feed)
        else:
            pair = (ex, sym)
        if pair not in seen:
            seen.add(pair)
            pairs.append(pair)
    return pairs


def tv_auto_probe_plan(symbol: str) -> list[tuple[str, str]]:
    equity = equity_tv_auto_probe_plan(symbol)
    if equity:
        return equity
    return tv_forex_auto_probe_plan(symbol)


def equity_tv_auto_probe_plan(symbol: str) -> list[tuple[str, str]]:
    from data.tradingview.symbol_lookup import lookup_tv_symbol_by_name, is_tv_name_input

    upper = (symbol or "").strip().upper()
    if upper in _KNOWN_INDEX_TICKERS:
        return _KNOWN_INDEX_TICKERS[upper]

    if is_tv_name_input(symbol):
        hit = lookup_tv_symbol_by_name(symbol)
        if hit is not None:
            return [hit]
        return []

    code_a = normalize_ashare_tv_code(symbol)
    if _is_ashare_tv_code(code_a):
        first = infer_ashare_tv_exchange(code_a)
        second = "SZSE" if first == "SSE" else "SSE"
        return [(first, code_a), (second, code_a)]

    code_h = normalize_hk_tv_code(symbol)
    if _is_hk_tv_code(code_h):
        return [(TV_HK_EXCHANGE, code_h)]

    if is_likely_crypto_symbol(upper):
        hint_ex = _CRYPTO_SYMBOL_EXCHANGE_HINTS.get(upper)
        pairs: list[tuple[str, str]] = []
        if hint_ex:
            pairs.append((hint_ex, upper))
        for ex in TV_CRYPTO_EXCHANGES:
            if ex != hint_ex:
                pairs.append((ex, upper))
        return pairs

    return []


def ashare_tv_probe_order(code: str) -> tuple[str, str]:
    first = infer_ashare_tv_exchange(code)
    second = "SZSE" if first == "SSE" else "SSE"
    return first, second


def is_hk_tv_request(exchange: str, symbol: str) -> bool:
    ex = (exchange or "").strip().upper()
    if ex in TV_HK_EXCHANGES:
        return True
    return _is_hk_tv_code(normalize_hk_tv_code(symbol))


def is_ashare_tv_request(exchange: str, symbol: str) -> bool:
    ex = (exchange or "").strip().upper()
    if ex in TV_ASHARE_EXCHANGES or ex in {"SH", "SZ", "SHSE", "XSHE", "SHANGHAI", "SHENZHEN"}:
        return True
    return _is_ashare_tv_code(normalize_ashare_tv_code(symbol))


def is_equity_tv_request(exchange: str, symbol: str) -> bool:
    from data.tradingview.symbol_lookup import is_tv_name_input

    if is_tv_name_input(symbol):
        return True
    return is_ashare_tv_request(exchange, symbol) or is_hk_tv_request(exchange, symbol)


def resolve_tv_ashare_pair(
    exchange: str,
    symbol: str,
) -> tuple[str, str, bool] | None:
    code = normalize_ashare_tv_code(symbol)
    if not _is_ashare_tv_code(code):
        return None

    ex_in = (exchange or "").strip().upper()
    adjusted = False
    if ex_in in ("SH", "SSE", "SHSE", "SHANGHAI"):
        return "SSE", code, ex_in != "SSE"
    if ex_in in ("SZ", "SZSE", "XSHE", "SHENZHEN"):
        required = infer_ashare_tv_exchange(code)
        if required == "SSE":
            return "SSE", code, True
        return "SZSE", code, ex_in != "SZSE"
    if ex_in in TV_ASHARE_EXCHANGES:
        required = infer_ashare_tv_exchange(code)
        if ex_in != required:
            return required, code, True
        return ex_in, code, False
    if is_tv_exchange_auto(ex_in):
        return "", code, False
    inferred = infer_ashare_tv_exchange(code)
    return inferred, code, True


def resolve_tv_hk_pair(
    exchange: str,
    symbol: str,
) -> tuple[str, str, bool] | None:
    code = normalize_hk_tv_code(symbol)
    if not _is_hk_tv_code(code):
        return None

    ex_in = (exchange or "").strip().upper()
    if ex_in in TV_HK_EXCHANGES:
        return TV_HK_EXCHANGE, code, ex_in != TV_HK_EXCHANGE
    if ex_in in TV_ASHARE_EXCHANGES:
        return TV_HK_EXCHANGE, code, True
    if is_tv_exchange_auto(ex_in):
        return "", code, False
    if ex_in in TV_GOLD_SYMBOL_BY_EXCHANGE:
        return TV_HK_EXCHANGE, code, True
    return TV_HK_EXCHANGE, code, True


def resolve_tv_fetch_pair(exchange: str, symbol: str) -> tuple[str, str]:
    from data.tradingview.symbol_lookup import (
        is_tv_name_input,
        lookup_tv_symbol_by_name,
    )

    ex = (exchange or "").strip().upper()
    sym = (symbol or "").strip()
    if is_tv_exchange_auto(ex):
        return "", sym
    if is_tv_name_input(sym):
        hit = lookup_tv_symbol_by_name(sym)
        if hit is not None:
            return hit
    return ex, sym


def resolve_tv_pair(
    exchange: str,
    symbol: str,
) -> tuple[str, str, bool]:
    from data.tradingview.symbol_lookup import (
        is_tv_name_input,
        lookup_tv_symbol_by_name,
    )

    sym = (symbol or "").strip()
    ex_in = (exchange or "").strip().upper()

    if is_tv_name_input(sym):
        hit = lookup_tv_symbol_by_name(sym)
        if hit is not None:
            ex_res, code = hit
            return ex_res, code, True

    upper = sym.upper()
    if upper in _KNOWN_INDEX_TICKERS:
        plan = _KNOWN_INDEX_TICKERS[upper]
        if is_tv_exchange_auto(ex_in):
            return plan[0][0], plan[0][1], True
        for ex_try, sym_try in plan:
            if ex_try == ex_in:
                return ex_try, sym_try, False
        return ex_in, sym, False

    ashare = resolve_tv_ashare_pair(exchange, symbol)
    if ashare is not None:
        return ashare

    hk = resolve_tv_hk_pair(exchange, symbol)
    if hk is not None:
        return hk

    if is_likely_crypto_symbol(upper):
        if is_tv_exchange_auto(ex_in):
            hint_ex = _CRYPTO_SYMBOL_EXCHANGE_HINTS.get(upper, TV_CRYPTO_EXCHANGES[0])
            return hint_ex, upper, True
        return ex_in, upper, False

    return resolve_tv_gold_pair(exchange, symbol)


def resolve_tv_gold_pair(
    exchange: str,
    symbol: str,
) -> tuple[str, str, bool]:
    ex_in = (exchange or "").strip().upper()
    sym = (symbol or "").strip().upper()
    if is_numeric_tv_equity_symbol(sym):
        hk = normalize_hk_tv_code(sym)
        if _is_hk_tv_code(hk):
            sym = hk
        if is_tv_exchange_auto(ex_in):
            return "", sym, False
        if ex_in in TV_EQUITY_EXCHANGES:
            return ex_in, sym, False
        return ex_in or "", sym, False
    if is_tv_exchange_auto(ex_in):
        return "", sym or GOLD_TV_SYMBOL, False
    ex = normalize_gold_tv_exchange(exchange)
    sym = sym or GOLD_TV_SYMBOL
    expected = TV_GOLD_SYMBOL_BY_EXCHANGE.get(ex)
    if expected is not None:
        if sym != expected:
            return ex, expected, True
        return ex, expected, False
    if sym == "GOLD":
        return "TVC", "GOLD", ex != "TVC"
    return GOLD_TV_EXCHANGE, GOLD_TV_SYMBOL, ex != GOLD_TV_EXCHANGE or sym != GOLD_TV_SYMBOL


def migrate_general_gold_defaults(general: dict) -> None:
    kind = str(general.get("last_data_source", "mt5"))
    sym = str(general.get("last_symbol", ""))
    general["last_symbol"] = normalize_gold_symbol_for_kind(kind, sym)
    if kind == "tradingview":
        ex, sym, _ = resolve_tv_pair(
            str(general.get("last_tradingview_exchange", "")),
            general["last_symbol"],
        )
        general["last_tradingview_exchange"] = ex
        general["last_symbol"] = sym
    else:
        general["last_tradingview_exchange"] = normalize_gold_tv_exchange(
            str(general.get("last_tradingview_exchange", ""))
        )
