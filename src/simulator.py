"""
仮想通貨自動売買Bot - 仮想約定エンジン
target_position ベースのポジション調整 (ロングのみ: 0.0 ~ 1.0)
"""
import logging
from datetime import datetime, timezone

from src.config import (
    INITIAL_BALANCE, TOTAL_COST_RATE,
    CIRCUIT_BREAKER_THRESHOLD, POSITION_CHANGE_THRESHOLD,
)
from src.database import (
    get_bot_state, update_bot_state, save_trade,
    save_balance_snapshot, get_positions,
)

logger = logging.getLogger(__name__)


class Simulator:
    """
    仮想約定エンジン (target_position ベース)。

    - 各botの仮想残高・ポジションを管理
    - target_position と current_position の差分でトレード実行
    - バー終値で判断 → 次バー始値 (= 現バー終値近似) で約定
    """

    def __init__(self, bot_name: str):
        self.bot_name = bot_name
        self._load_state()

    def _load_state(self):
        """データベースからボット状態を読み込む。"""
        state = get_bot_state(self.bot_name)
        if state:
            self.balance = state["balance"]
            self.is_active = bool(state["is_active"])
        else:
            self.balance = INITIAL_BALANCE
            self.is_active = True

        # ポジション: {symbol: position_ratio}
        # position_ratio = 0.0 (ノーポジ) ~ 1.0 (フルロング)
        # 実際には「保有数量」で管理し、比率は total_asset で計算
        positions = get_positions(self.bot_name)
        self.quantities = {}
        for symbol, data in positions.items():
            self.quantities[symbol] = data["position"]

    def apply_signal(self, symbol: str, signal: dict, current_price: float) -> dict:
        """
        target_position に基づいてポジション調整する。

        Args:
            symbol: 銘柄ペア
            signal: {"target_position": 0.0~1.0, "confidence": float, "reason": str}
            current_price: 現在価格

        Returns:
            dict: 取引結果
        """
        if not self.is_active:
            return {"executed": False, "reason": "サーキットブレーカーにより停止中"}

        target_pos = signal.get("target_position", 0.0)
        confidence = signal.get("confidence", 0.0)
        reason = signal.get("reason", "")

        # 現在のポジション比率を計算
        total_asset = self._total_asset({symbol: current_price})
        current_qty = self.quantities.get(symbol, 0.0)
        current_value = current_qty * current_price
        current_pos = current_value / total_asset if total_asset > 0 else 0.0

        # ポジション変更の差分
        delta = target_pos - current_pos

        # 閾値以下の変更はスキップ（コスト負け防止）
        if abs(delta) < POSITION_CHANGE_THRESHOLD:
            return {
                "executed": False,
                "reason": f"変更幅不足 (delta={delta:.3f})",
                "current_pos": current_pos,
                "target_pos": target_pos,
            }

        now = datetime.now(timezone.utc).isoformat()

        if delta > 0:
            result = self._increase_position(
                symbol, current_price, delta, total_asset,
                target_pos, current_pos, confidence, now, reason
            )
        else:
            result = self._decrease_position(
                symbol, current_price, abs(delta), total_asset,
                target_pos, current_pos, confidence, now, reason
            )

        # サーキットブレーカーチェック
        if not self._check_circuit_breaker({symbol: current_price}):
            self.is_active = False
            update_bot_state(self.bot_name, self.balance, is_active=False)

        return result

    def _increase_position(self, symbol, price, delta, total_asset,
                           target_pos, prev_pos, confidence, timestamp, reason):
        """ポジションを増やす (買い)。"""
        # 購入金額 = total_asset × delta
        buy_amount = total_asset * delta

        if buy_amount > self.balance:
            buy_amount = self.balance  # 残高上限

        if buy_amount <= 0:
            return {"executed": False, "reason": "残高不足"}

        effective_price = price * (1 + TOTAL_COST_RATE)
        quantity = buy_amount / effective_price

        self.balance -= buy_amount
        self.quantities[symbol] = self.quantities.get(symbol, 0.0) + quantity

        save_trade(
            timestamp=timestamp, bot_name=self.bot_name, symbol=symbol,
            action="BUY", price=price, effective_price=effective_price,
            quantity=quantity, balance=self.balance,
            position=self.quantities[symbol],
            target_position=target_pos, prev_position=prev_pos,
            confidence=confidence, note=reason,
        )
        update_bot_state(self.bot_name, self.balance)

        logger.info(
            f"[{self.bot_name}] BUY {symbol}: "
            f"pos {prev_pos:.2f}→{target_pos:.2f}, qty={quantity:.6f}, "
            f"残高={self.balance:.0f}"
        )
        return {
            "executed": True, "action": "BUY", "symbol": symbol,
            "quantity": quantity, "price": price,
            "effective_price": effective_price,
            "balance": self.balance,
            "prev_pos": prev_pos, "target_pos": target_pos,
        }

    def _decrease_position(self, symbol, price, delta, total_asset,
                           target_pos, prev_pos, confidence, timestamp, reason):
        """ポジションを減らす (売り)。"""
        current_qty = self.quantities.get(symbol, 0.0)
        if current_qty <= 0:
            return {"executed": False, "reason": f"{symbol}のポジションなし"}

        # 売却数量 = (delta / prev_pos) × current_qty (比率分だけ売却)
        if prev_pos > 0:
            sell_ratio = min(1.0, delta / prev_pos)
        else:
            sell_ratio = 1.0

        sell_quantity = current_qty * sell_ratio

        effective_price = price * (1 - TOTAL_COST_RATE)
        sale_amount = sell_quantity * effective_price

        self.balance += sale_amount
        self.quantities[symbol] = current_qty - sell_quantity

        # PnL は概算 (売却額 - 元の投資額)
        # 正確なPnLは平均取得価格が必要だが、簡易版ではコスト差分のみ
        profit_loss = sell_quantity * (effective_price - price)

        save_trade(
            timestamp=timestamp, bot_name=self.bot_name, symbol=symbol,
            action="SELL", price=price, effective_price=effective_price,
            quantity=sell_quantity, balance=self.balance,
            position=self.quantities[symbol],
            target_position=target_pos, prev_position=prev_pos,
            profit_loss=profit_loss, confidence=confidence, note=reason,
        )
        update_bot_state(self.bot_name, self.balance)

        logger.info(
            f"[{self.bot_name}] SELL {symbol}: "
            f"pos {prev_pos:.2f}→{target_pos:.2f}, qty={sell_quantity:.6f}, "
            f"残高={self.balance:.0f}"
        )
        return {
            "executed": True, "action": "SELL", "symbol": symbol,
            "quantity": sell_quantity, "price": price,
            "effective_price": effective_price,
            "balance": self.balance, "profit_loss": profit_loss,
            "prev_pos": prev_pos, "target_pos": target_pos,
        }

    def _total_asset(self, current_prices: dict) -> float:
        """総資産を計算する。"""
        position_value = 0
        for sym, qty in self.quantities.items():
            if sym in current_prices and qty > 0:
                position_value += qty * current_prices[sym]
        return self.balance + position_value

    def _check_circuit_breaker(self, current_prices: dict) -> bool:
        """サーキットブレーカー判定。"""
        total = self._total_asset(current_prices)
        loss_rate = (INITIAL_BALANCE - total) / INITIAL_BALANCE
        if loss_rate >= CIRCUIT_BREAKER_THRESHOLD:
            logger.warning(
                f"[{self.bot_name}] ⚠️ サーキットブレーカー発動！ "
                f"総資産: {total:.0f} (損失率: {loss_rate:.1%})"
            )
            return False
        return True

    def save_snapshot(self, current_prices: dict, trade_count: int = 0):
        """残高スナップショットを保存する。"""
        position_value = sum(
            qty * current_prices.get(sym, 0)
            for sym, qty in self.quantities.items()
            if qty > 0
        )
        total_asset = self.balance + position_value
        total_pnl = total_asset - INITIAL_BALANCE

        save_balance_snapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            bot_name=self.bot_name,
            balance=self.balance,
            total_position_value=position_value,
            total_asset=total_asset,
            daily_pnl=0,
            total_pnl=total_pnl,
            trade_count=trade_count,
            is_active=self.is_active,
        )
