"""
trading_mode.py
================

This module manages both virtual and real trading modes for the Upbit cryptocurrency
exchange. It encapsulates logic for logging trades, resetting virtual trade history,
fetching account information, and placing buy/sell orders. The behaviour of the class
is driven by a small JSON configuration file (``config.json``) which specifies
whether the application should run in ``virtual`` mode (default) or ``real`` mode.

When running in virtual mode, trades are not sent to Upbit; instead, they are
recorded to a log file. When running in real mode the module uses ``pyupbit`` to
interact with the Upbit API. Only coins listed in the ``coins`` field of the
configuration will be traded or displayed. A log file is maintained across
sessions to preserve continuity while testing. A reset mechanism is provided
which clears the log file; it may only be called when running in virtual mode.

This design keeps the trading logic isolated from any web interface or
automation code and makes it easy to unit‑test the behaviour independently.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

try:
    import pyupbit
except ImportError:
    # ``pyupbit`` may not be installed in the environment by default. When this
    # module is imported in virtual mode no interaction with Upbit occurs, so
    # missing dependencies are gracefully tolerated. If real trading is enabled
    # at runtime and the library is unavailable an exception will be raised.
    pyupbit = None


class TradingMode:
    """Encapsulates state and operations for both virtual and real trading modes.

    Parameters
    ----------
    config_path : str, optional
        Path to the JSON configuration file. Defaults to ``config.json``.

    Attributes
    ----------
    virtual : bool
        True when running in virtual mode, False for real mode.
    coins : List[str]
        List of coin symbols allowed for trading/displaying. These symbols are
        interpreted as KRW pairs (e.g. ``"BTC"`` becomes ``"KRW-BTC"`` when
        placing orders).
    log_file : str
        Path to the log file that records all trade activity.
    upbit : Optional[pyupbit.Upbit]
        Upbit client used only in real mode. None when running virtually.
    config : Dict
        Raw configuration dictionary loaded from the JSON file.
    """

    def __init__(self, config_path: str = "config.json") -> None:
        # Load configuration from disk. If the file is missing a clear error
        # will propagate to alert the operator early.
        with open(config_path, "r", encoding="utf-8") as cf:
            self.config: Dict = json.load(cf)

        # Determine whether we are running virtually. Anything other than the
        # literal string ``"real"`` will be treated as virtual to avoid
        # accidental real trades.
        self.virtual: bool = self.config.get("mode", "virtual").lower() != "real"

        # Load allowed coin list. Fall back to an empty list if unspecified.
        self.coins: List[str] = self.config.get("coins", [])

        # Resolve log file path. A relative path will be created in the
        # application working directory.
        self.log_file: str = self.config.get("log_file", "trading.log")

        # Initialise Upbit client only when real trades are enabled. This
        # safeguards against inadvertently instantiating the client when
        # credentials are absent or ``pyupbit`` is missing.
        self.upbit: Optional["pyupbit.Upbit"] = None
        if not self.virtual:
            if pyupbit is None:
                raise ImportError(
                    "pyupbit must be installed to run in real trading mode."
                )
            access_key = self.config.get("access_key")
            secret_key = self.config.get("secret_key")
            if not access_key or not secret_key:
                raise ValueError(
                    "Upbit access_key and secret_key must be provided in config.json"
                )
            # Create Upbit client instance
            self.upbit = pyupbit.Upbit(access_key, secret_key)

        # Ensure log file exists for appending; do not truncate existing logs.
        if not os.path.exists(self.log_file):
            open(self.log_file, "w", encoding="utf-8").close()

    # ------------------------------------------------------------------
    # Internal helpers
    #
    def _timestamp(self) -> str:
        """Return the current timestamp as a human‑readable string."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def log(self, message: str) -> None:
        """Append a timestamped message to the log file.

        Parameters
        ----------
        message : str
            Arbitrary text to record. A newline will be appended
            automatically.
        """
        line = f"{self._timestamp()} {message}\n"
        with open(self.log_file, "a", encoding="utf-8") as lf:
            lf.write(line)

    # ------------------------------------------------------------------
    # Public API
    #
    def reset_log(self) -> None:
        """Clear the trade log. Only permitted when in virtual mode.

        Calling this method truncates the log file so that subsequent test
        sessions start fresh. Attempting to reset while running in real
        mode raises a ``RuntimeError``.
        """
        if not self.virtual:
            raise RuntimeError("Log reset is only available in virtual mode")
        open(self.log_file, "w", encoding="utf-8").close()
        self.log("Log file reset by user request")

    def get_account_info(self) -> Dict:
        """Retrieve current account information.

        In virtual mode a minimal dictionary describing the mode is returned.
        In real mode the method queries the Upbit API for balances and
        constructs a dictionary keyed by coin symbol containing balance and
        average buy price.

        Returns
        -------
        Dict
            A dictionary summarising account status.
        """
        if self.virtual or self.upbit is None:
            return {"mode": "virtual", "message": "No real account connected"}

        balances = self.upbit.get_balances()
        account: Dict[str, Dict[str, float]] = {}
        for bal in balances:
            currency = bal.get("currency")
            # Upbit API may return ``None`` for missing fields; guard accordingly
            if currency and currency in self.coins:
                try:
                    balance = float(bal.get("balance", 0))
                    avg_price = float(bal.get("avg_buy_price", 0))
                except (TypeError, ValueError):
                    # Skip entries with non‑numeric values
                    continue
                account[currency] = {
                    "balance": balance,
                    "avg_buy_price": avg_price,
                }
        return account

    def trade(self, coin: str, amount: float, side: str) -> Optional[Dict]:
        """Execute a trade for the specified coin and amount.

        Parameters
        ----------
        coin : str
            Coin symbol (e.g. ``"BTC"``) to buy or sell. Must be present in
            the ``coins`` list.
        amount : float
            Amount of KRW to spend when buying or amount of coin to sell when
            selling. For consistency with Upbit's API the caller should
            specify the correct units for the given side.
        side : str
            Either ``"buy"`` or ``"sell"``. Any other value will raise a
            ``ValueError``.

        Returns
        -------
        Optional[Dict]
            In real mode the Upbit order response is returned; in virtual
            mode None is returned after logging the simulated trade.
        """
        if coin not in self.coins:
            raise ValueError(f"Coin '{coin}' is not allowed by configuration")
        side_lower = side.lower()
        if side_lower not in {"buy", "sell"}:
            raise ValueError("Parameter 'side' must be either 'buy' or 'sell'")

        if self.virtual or self.upbit is None:
            self.log(f"{side_upper(side_lower)} {coin} {amount} (virtual)")
            return None

        # Real trade; wrap Upbit calls in try/except to handle potential API
        # errors gracefully. We rely on Upbit's market order endpoints for
        # simplicity.
        market_symbol = f"KRW-{coin}"
        try:
            if side_lower == "buy":
                order = self.upbit.buy_market_order(market_symbol, amount)
            else:
                order = self.upbit.sell_market_order(market_symbol, amount)
        except Exception as exc:  # broad catch to log and rethrow
            self.log(f"ERROR executing {side_lower} for {coin}: {exc}")
            raise
        self.log(
            f"{side_upper(side_lower)} {coin} {amount} (real) order_id={order.get('uuid')}"
        )
        return order


def side_upper(side: str) -> str:
    """Return a properly capitalised side string for logging."""
    return "BUY" if side.lower() == "buy" else "SELL"


if __name__ == "__main__":
    # Demonstration stub: print current account info. This makes it simple
    # to run this module directly from the command line to check Upbit
    # connectivity. The call prints either a virtual mode message or a
    # dictionary of balances for the configured coins.
    tm = TradingMode()
    print(json.dumps(tm.get_account_info(), indent=2, ensure_ascii=False))
