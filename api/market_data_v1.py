"""Baostock V1 行情协议路由与 Baostock 字段转换。"""

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

router = APIRouter()
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

Period = Literal["1min", "5min", "15min", "30min", "60min", "daily", "weekly", "monthly"]
Adjustment = Literal["qfq", "hfq", "none", "splits"]


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
    """校验请求是否属于 Baostock Provider。"""
    if source_id != "baostock":
        return _failure(400, "INVALID_REQUEST", "sourceId must be baostock")
    return None


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


def _date_from_ms(value: int) -> str:
    """将 UTC 毫秒时间戳转换为上海时区日期。"""
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).astimezone(SHANGHAI_TZ).date().isoformat()


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


@router.get("/api/v1/market-data/sources/{sourceId}/probe", response_model=None)
def probe_market_data_source(source_id: str = Path(alias="sourceId")) -> dict | JSONResponse:
    """探测 Baostock 登录和上游可用性。"""
    error = _source_error(source_id)
    if error:
        return error
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
        return _success(data)
    except Exception as exc:
        return _success({
            "status": "offline",
            "checkedAt": int(datetime.now(timezone.utc).timestamp() * 1000),
            "latencyMs": round((time.perf_counter() - started) * 1000, 2),
            "message": str(exc),
        })
    finally:
        if login is not None and login.error_code == "0":
            bs.logout()


@router.post("/api/v1/market-data/instruments/search", response_model=None)
def search_instruments(request: InstrumentSearchRequest = Body(...)) -> dict | JSONResponse:
    """搜索 Baostock 股票目录并转换为 V1 品种描述。"""
    error = _source_error(request.sourceId)
    if error:
        return error
    if request.assetClasses is not None and "stock" not in request.assetClasses:
        return _success({"items": []})
    result = query_all_stock()
    if not result.get("success"):
        return _failure(502, "UPSTREAM_UNAVAILABLE", result.get("error_msg", "Baostock query failed"))
    keyword = request.keyword.casefold()
    items = []
    for row in result.get("data", []):
        code = str(row.get("code", ""))
        name = str(row.get("code_name", ""))
        if keyword in code.casefold() or keyword in name.casefold():
            items.append(_instrument(code, name))
            if len(items) >= request.limit:
                break
    return _success({"items": items})


@router.post("/api/v1/market-data/bars", response_model=None)
def fetch_bars(request: BarRequest) -> dict | JSONResponse:
    """按 V1 请求读取 Baostock 历史 K 线。"""
    error = _source_error(request.sourceId)
    if error:
        return error
    if request.from_ > request.to:
        return _failure(400, "INVALID_REQUEST", "to must not be earlier than from")
    if request.adjustment == "splits":
        return _failure(400, "UNSUPPORTED_CAPABILITY", "Baostock does not support splits adjustment")
    period_map = {"daily": "d", "weekly": "w", "monthly": "m", "5min": "5", "15min": "15", "30min": "30", "60min": "60"}
    if request.period not in period_map:
        return _failure(400, "UNSUPPORTED_CAPABILITY", f"Baostock does not support {request.period}")
    stock_code = str((request.instrument.providerRef or {}).get("stockCode") or request.instrument.symbol)
    result = get_stock_k_data(
        stock_code=stock_code,
        start_date=_date_from_ms(request.from_),
        end_date=_date_from_ms(request.to),
        frequency=period_map[request.period],
        adjustflag={"qfq": "2", "hfq": "1", "none": "3"}[request.adjustment],
    )
    if not result.get("success"):
        return _failure(502, "UPSTREAM_UNAVAILABLE", result.get("error_msg", "Baostock query failed"))
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
    return _success({
        "instrumentId": request.instrument.id,
        "period": request.period,
        "adjustment": request.adjustment,
        "timezone": "Asia/Shanghai",
        "volumeUnit": "share",
        "items": items,
    })


@router.post("/api/v1/market-data/timeshare")
def fetch_time_share(request: dict = Body(...)) -> JSONResponse:
    """声明 Baostock 当前尚未提供 V1 分时能力。"""
    source_id = str(request.get("sourceId", ""))
    error = _source_error(source_id)
    if error:
        return error
    return _failure(400, "UNSUPPORTED_CAPABILITY", "Baostock does not support timeshare")
