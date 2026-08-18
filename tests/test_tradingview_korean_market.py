"""TradingView 韩股市场识别与 V1 映射测试。"""

from unittest.mock import MagicMock, patch
import unittest

from api.market_data_v1 import (
    BarRequest,
    _fetch_tradingview_bars,
    _probe_tradingview,
    _tv_instrument,
)
from data.base import KlineBar
from data.tradingview.market_defaults import (
    is_known_index_tv_symbol,
    resolve_tv_pair,
    tv_auto_probe_plan,
)


class TradingViewKoreanMarketTest(unittest.TestCase):
    """验证六位代码可同时保留中韩候选且显式 KRX 不被改写。"""

    def test_six_digit_code_includes_korean_candidate(self):
        """裸六位代码同时返回 A 股和 KRX 候选。"""
        plan = tv_auto_probe_plan("005930")

        self.assertIn(("KRX", "005930"), plan)
        self.assertTrue(any(exchange in {"SSE", "SZSE"} for exchange, _ in plan))

    def test_explicit_krx_selection_is_preserved(self):
        """显式 KRX 选择优先于 A 股六位代码推断。"""
        self.assertEqual(resolve_tv_pair("KRX", "005930"), ("KRX", "005930", False))

    def test_known_index_helper_keeps_private_mapping_encapsulated(self):
        """API 层通过公共判断函数识别指数，不依赖私有映射实现。"""
        self.assertTrue(is_known_index_tv_symbol("spx"))
        self.assertFalse(is_known_index_tv_symbol("005930"))

    def test_v1_instrument_uses_korean_market_metadata(self):
        """韩股品种描述返回 KR 会话、KRW 币种和股票类型。"""
        instrument = _tv_instrument("005930", "KRX")

        self.assertEqual(instrument["exchange"], "KRX")
        self.assertEqual(instrument["sessionId"], "KR")
        self.assertEqual(instrument["currency"], "KRW")
        self.assertEqual(instrument["assetClass"], "stock")

    def test_probe_declares_stock_bar_capabilities_for_source_routing(self):
        """TradingView 探测结果应允许 Router 为韩股选择股票 K 线能力。"""
        result = _probe_tradingview()

        self.assertIn("stock", result["capabilities"]["assetClasses"])
        self.assertIn("daily", result["capabilities"]["bars"]["periods"])
        self.assertIn("none", result["capabilities"]["bars"]["adjustments"])

    def test_v1_bars_keep_krx_and_seoul_timezone(self):
        """韩股 K 线请求保持 KRX 并返回首尔时区。"""
        source = MagicMock()
        source.latest_snapshot.return_value = [
            KlineBar(
                seq=1,
                ts_open=1_000,
                open=1,
                high=2,
                low=1,
                close=2,
                volume=3,
                closed=True,
            )
        ]
        request = BarRequest.model_validate(
            {
                "sourceId": "tradingview",
                "instrument": {
                    "id": "tradingview:KRX:005930",
                    "symbol": "005930",
                    "exchange": "KRX",
                    "providerRef": {"exchange": "KRX", "symbol": "005930"},
                },
                "period": "daily",
                "adjustment": "none",
                "limit": 10,
            }
        )

        with patch("api.market_data_v1.TradingViewSource", return_value=source):
            result = _fetch_tradingview_bars(request)

        source.set_exchange.assert_called_once_with("KRX")
        source.subscribe.assert_called_once_with("005930", "1d")
        self.assertEqual(result["timezone"], "Asia/Seoul")


if __name__ == "__main__":
    unittest.main()
