"""Baostock / TradingView V1 行情协议路由与字段转换。"""

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4
import time
from zoneinfo import ZoneInfo

import baostock as bs
from fastapi import APIRouter, Body, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from stock_service import get_stock_k_data, query_all_stock
from data.tradingview.source import TradingViewSource
from data.tradingview.market_defaults import tv_auto_probe_plan
from data.tradingview.symbol_lookup import lookup_tv_symbol_by_name
from data.datetime_ts import epoch_to_date_str

router = APIRouter()
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

Period = Literal["1min", "5min", "15min", "30min", "60min", "daily", "weekly", "monthly"]
Adjustment = Literal["qfq", "hfq", "none", "splits"]

# 允许的 V1 数据源 ID
_SUPPORTED_SOURCES = frozenset({"baostock", "tradingview"})

# TradingView 周期/复权到 tvDatafeed 的映射
_TV_PERIODS = ["1min", "5min", "15min", "30min", "60min", "daily", "weekly", "monthly"]
_TV_PERIOD_TO_TF = {
    "1min": "1m",
    "5min": "5m",
    "15min": "15m",
    "30min": "30m",
    "60min": "1h",
    "daily": "1d",
    "weekly": "1w",
    "monthly": "1M",
}
_TV_ADJUST_TO_TF = {"qfq": "dividends", "splits": "splits", "none": "none"}

# 会话/币种/时区按品种类型推断
_TV_SESSION_TZ = {
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "US": "America/New_York",
}


class InstrumentReference(BaseModel):
    """V1 请求中的品种引用。"""

    id: str
    symbol: str
    exchange: str
    providerRef: dict[str, str | int | float | bool] | None = None


class InstrumentSearchRequest(BaseModel):
    """V1 品种搜索请求。"""

    sourceId: str = Field(min_length=1)
    keyword: str = Field(min_length=1, max_length=128)
    limit: int = Field(ge=1, le=100)
    assetClasses: list[str] | None = None


class BarRequest(BaseModel):
    """V1 K 线查询请求。"""

    sourceId: str = Field(min_length=1)
    instrument: InstrumentReference
    period: Period
    adjustment: Adjustment
    from_: int = Field(alias="from")
    to: int

    model_config = {"populate_by_name": True}


def _request_id() -> str:
    """生成请求追踪 ID。"""
    return str(uuid4())


def _success(data: object) -> dict[str, object]:
    """包装 V1 成功响应。"""
    return {"data": data, "requestId": _request_id()}


def _failure(status: int, code: str, message: str, details: Optional[dict] = None) -> JSONResponse:
    """构造 V1 标准错误响应。"""
    error: dict[str, object] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return JSONResponse(status_code=status, content={"error": error, "requestId": _request_id()})


def _source_error(source_id: str) -> Optional[JSONResponse]:
    """校验请求是否属于受支持的数据源。"""
    if source_id not in _SUPPORTED_SOURCES:
        return _failure(
            400, "INVALID_REQUEST", f"sourceId must be one of {sorted(_SUPPORTED_SOURCES)}"
        )
    return None


def _date_from_ms(value: int) -> str:
    """将 UTC 毫秒时间戳转换为上海时区日期。"""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).astimezone(SHANGHAI_TZ).date().isoformat()


# ---------- Baostock ----------

def _instrument(code: str, name: str) -> dict[str, object]:
    """将 Baostock 股票记录转换为 V1 品种描述。"""
    market, symbol = code.split(".", 1) if "." in code else ("", code)
    exchange = {"sh": "SH", "sz": "SZ", "bj": "BJ"}.get(market.lower(), market.upper())
    return {
        "id": f"baostock:stock:{market.lower()}:{symbol}",
        "sourceId": "baostock",
        "symbol": code,
        "name": name or symbol,
        "assetClass": "stock",
        "exchange": exchange,
        "sessionId": "CN",
        "currency": "CNY",
        "providerRef": {"stockCode": code},
        "capabilities": {
            "bars": {
                "periods": ["5min", "15min", "30min", "60min", "daily", "weekly", "monthly"],
                "adjustments": ["qfq", "hfq", "none"],
            }
        },
    }


def _timestamp_ms(item: dict[str, object]) -> int:
    """将 Baostock 日期或分钟时间转换为 UTC 毫秒时间戳。"""
    raw_time = str(item.get("time") or "")
    digits = "".join(char for char in raw_time if char.isdigit())
    if len(digits) >= 14:
        local = datetime.strptime(digits[:14], "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI_TZ)
    else:
        local = datetime.strptime(str(item["date"])[:10], "%Y-%m-%d").replace(tzinfo=SHANGHAI_TZ)
    return int(local.timestamp() * 1000)


def _number(value: object) -> Optional[float]:
    """将 Baostock 空字符串或数字转换为可选浮点数。"""
    if value is None or value == "":
        return None
    return float(value)


def _probe_baostock() -> dict:
    """探测 Baostock 登录与上游可用性。"""
    started = time.perf_counter()
    login = None
    try:
        login = bs.login()
        online = login.error_code == "0"
        data = {
            "status": "online" if online else "offline",
            "checkedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
            "latencyMs": round((time.perf_counter() - started) * 1000, 2),
        }
        if not online:
            data["message"] = login.error_msg
        return data
    except Exception as exc:
        return {
            "status": "offline",
            "checkedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
            "latencyMs": round((time.perf_counter() - started) * 1000, 2),
            "message": str(exc),
        }
    finally:
        if login is not None and login.error_code == "0":
            bs.logout()


def _search_baostock(request: InstrumentSearchRequest) -> dict:
    """搜索 Baostock 股票目录并转换为 V1 品种描述。"""
    if request.assetClasses is not None and "stock" not in request.assetClasses:
        return {"items": []}
    result = query_all_stock()
    if not result.get("success"):
        raise _UpstreamError(result.get("error_msg", "Baostock query failed"))
    keyword = request.keyword.casefold()
    items = []
    for row in result.get("data", []):
        code = str(row.get("code", ""))
        name = str(row.get("code_name", ""))
        if keyword in code.casefold() or keyword in name.casefold():
            items.append(_instrument(code, name))
            if len(items) >= request.limit:
                break
    return {"items": items}


def _fetch_baostock_bars(request: BarRequest) -> dict:
    """按 V1 请求读取 Baostock 历史 K 线。"""
    if request.from_ > request.to:
        raise _RequestError("to must not be earlier than from")
    if request.adjustment == "splits":
        raise _CapabilityError("Baostock does not support splits adjustment")
    period_map = {"daily": "d", "weekly": "w", "monthly": "m", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
    if request.period not in period_map:
        raise _CapabilityError(f"Baostock does not support {request.period}")
    stock_code = str((request.instrument.providerRef or {}).get("stockCode") or request.instrument.symbol)
    result = get_stock_k_data(
        stock_code=stock_code,
        start_date=_date_from_ms(request.from_),
        end_date=_date_from_ms(request.to),
        frequency=period_map[request.period],
        adjustflag={"qfq": "2", "hfq": "1", "none": "3"}[request.adjustment],
    )
    if not result.get("success"):
        raise _UpstreamError(result.get("error_msg", "Baostock query failed"))
    items = []
    for row in result.get("data", []):
        timestamp = _timestamp_ms(row)
        if not request.from_ <= timestamp <= request.to:
            continue
        items.append({
            "timestamp": timestamp,
            "date": str(row.get("date", "")),
            "open": _number(row.get("open")),
            "high": _number(row.get("high")),
            "low": _number(row.get("low")),
            "close": _number(row.get("close")),
            "volume": _number(row.get("volume")),
            "turnover": _number(row.get("amount")),
            "changePercent": _number(row.get("pctChg")),
            "turnoverRate": _number(row.get("turn")),
        })
    return {
        "instrumentId": request.instrument.id,
        "period": request.period,
        "adjustment": request.adjustment,
        "timezone": "Asia/Shanghai",
        "volumeUnit": "share",
        "items": items,
    }


# ---------- TradingView ----------

def _tv_session(symbol: str, exchange: str) -> str:
    """按品种/交易所推断交易时段标识。"""
    from data.tradingview.market_defaults import (
        is_ashare_tv_request,
        is_hk_tv_request,
    )

    if is_ashare_tv_request(exchange, symbol):
        return "CN"
    if is_hk_tv_request(exchange, symbol):
        return "HK"
    return "US"


def _tv_asset_class(symbol: str, exchange: str) -> str:
    """按品种/交易所推断资产类别。"""
    from data.tradingview.market_defaults import (
        _KNOWN_INDEX_TICKERS,
        is_ashare_tv_request,
        is_hk_tv_request,
        is_likely_crypto_symbol,
    )

    upper = symbol.upper()
    if upper in _KNOWN_INDEX_TICKERS:
        return "index"
    if upper in ("XAUUSD", "GOLD", "XAGUSD") or "/" in upper:
        return "forex"
    if is_likely_crypto_symbol(upper):
        return "crypto"
    if is_ashare_tv_request(exchange, symbol) or is_hk_tv_request(exchange, symbol):
        return "stock"
    return "unknown"


def _tv_instrument(symbol: str, exchange: str = "") -> dict[str, object]:
    """将 TradingView 代码转换为 V1 品种描述。"""
    sym = (symbol or "").strip()
    ex = (exchange or "").strip().upper()
    session = _tv_session(sym, ex)
    currency = {"CN": "CNY", "HK": "HKD"}.get(session, "USD")
    return {
        "id": f"tradingview:{ex or 'auto'}:{sym}",
        "sourceId": "tradingview",
        "symbol": sym,
        "name": sym,
        "assetClass": _tv_asset_class(sym, ex),
        "exchange": ex or "AUTO",
        "sessionId": session,
        "currency": currency,
        "providerRef": {"exchange": ex, "symbol": sym},
        "capabilities": {
            "bars": {
                "periods": _TV_PERIODS,
                "adjustments": ["qfq", "splits", "none"],
            }
        },
    }


def _probe_tradingview() -> dict:
    """探测 tvDatafeed 是否可导入（TradingView 无本地登录状态）。"""
    started = time.perf_counter()
    try:
        import tvDatafeed  # noqa: F401

        return {
            "status": "online",
            "checkedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
            "latencyMs": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:
        return {
            "status": "offline",
            "checkedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
            "latencyMs": round((time.perf_counter() - started) * 1000, 2),
            "message": str(exc),
        }


def _search_tradingview(request: InstrumentSearchRequest) -> dict:
    """按名称映射或自动探测推断 TradingView 品种。"""
    keyword = request.keyword.strip()
    items = []
    seen = set()

    def add(symbol: str, exchange: str) -> None:
        key = f"{exchange}:{symbol}"
        if key in seen:
            return
        seen.add(key)
        items.append(_tv_instrument(symbol, exchange))

    hit = lookup_tv_symbol_by_name(keyword)
    if hit is not None:
        add(hit[1], hit[0])
    for ex, sym in tv_auto_probe_plan(keyword):
        add(sym, ex)
    if not items:
        add(keyword, "")
    if request.assetClasses:
        allowed = set(request.assetClasses)
        items = [item for item in items if item.get("assetClass") in allowed]
    return {"items": items[: request.limit]}


def _fetch_tradingview_bars(request: BarRequest) -> dict:
    """按 V1 请求通过 TradingView 拉取历史 K 线。"""
    if request.from_ > request.to:
        raise _RequestError("to must not be earlier than from")
    if request.adjustment == "hfq":
        raise _CapabilityError("TradingView does not support hfq adjustment")
    timeframe = _TV_PERIOD_TO_TF.get(request.period)
    if timeframe is None:
        raise _CapabilityError(f"TradingView does not support {request.period}")
    adjust = _TV_ADJUST_TO_TF.get(request.adjustment, "none")
    ref = request.instrument.providerRef or {}
    exchange = str(ref.get("exchange") or request.instrument.exchange or "")
    symbol = str(ref.get("symbol") or request.instrument.symbol)
    try:
        src = TradingViewSource(adjust=adjust)
        src.connect()
        try:
            src.set_exchange(exchange)
            src.subscribe(symbol, timeframe)
            bars, _warning = src.fetch_range(
                _date_from_ms(request.from_),
                _date_from_ms(request.to),
            )
        finally:
            src.disconnect()
    except Exception as exc:
        raise _UpstreamError(str(exc))
    session = _tv_session(symbol, exchange)
    items = []
    for bar in bars:
        ts_ms = int(bar.ts_open)
        if not request.from_ <= ts_ms <= request.to:
            continue
        items.append({
            "timestamp": ts_ms,
            "date": epoch_to_date_str(bar.ts_open),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
        })
    return {
        "instrumentId": request.instrument.id,
        "period": request.period,
        "adjustment": request.adjustment,
        "timezone": _TV_SESSION_TZ.get(session, "UTC"),
        "items": items,
    }


# ---------- 统一异常到错误响应 ----------

class _RequestError(Exception):
    """请求不合法。"""

    code = "INVALID_REQUEST"


class _CapabilityError(Exception):
    """请求能力不受支持。"""

    code = "UNSUPPORTED_CAPABILITY"


class _UpstreamError(Exception):
    """上游查询失败。"""

    code = "UPSTREAM_UNAVAILABLE"


def _dispatch(func, *args, **kwargs) -> dict | JSONResponse:
    """执行数据源处理函数，把领域异常转为 V1 错误响应。"""
    try:
        return _success(func(*args, **kwargs))
    except _RequestError as exc:
        return _failure(400, exc.code, str(exc))
    except _CapabilityError as exc:
        return _failure(400, exc.code, str(exc))
    except _UpstreamError as exc:
        return _failure(502, exc.code, str(exc))


_HANDLERS = {
    "probe": {"baostock": _probe_baostock, "tradingview": _probe_tradingview},
    "search": {"baostock": _search_baostock, "tradingview": _search_tradingview},
    "bars": {"baostock": _fetch_baostock_bars, "tradingview": _fetch_tradingview_bars},
}


@router.get("/api/v1/market-data/sources/{sourceId}/probe", response_model=None)
def probe_market_data_source(source_id: str = Path(alias="sourceId")) -> dict | JSONResponse:
    """探测数据源可用性。"""
    error = _source_error(source_id)
    if error:
        return error
    return _dispatch(_HANDLERS["probe"][source_id])


@router.post("/api/v1/market-data/instruments/search", response_model=None)
def search_instruments(request: InstrumentSearchRequest = Body(...)) -> dict | JSONResponse:
    """搜索数据源标准品种目录。"""
    error = _source_error(request.sourceId)
    if error:
        return error
    return _dispatch(_HANDLERS["search"][request.sourceId], request)


@router.post("/api/v1/market-data/bars", response_model=None)
def fetch_bars(request: BarRequest) -> dict | JSONResponse:
    """按 V1 请求读取数据源历史 K 线。"""
    error = _source_error(request.sourceId)
    if error:
        return error
    return _dispatch(_HANDLERS["bars"][request.sourceId], request)


@router.post("/api/v1/market-data/timeshare")
def fetch_time_share(request: dict = Body(...)) -> JSONResponse:
    """声明当前数据源均未提供 V1 分时能力。"""
    source_id = str(request.get("sourceId", ""))
    error = _source_error(source_id)
    if error:
        return error
    return _failure(400, "UNSUPPORTED_CAPABILITY", f"{source_id} does not support timeshare")
