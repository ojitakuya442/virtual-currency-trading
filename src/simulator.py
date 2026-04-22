"""
仮想通貨自動売買Bot - 仮想約定エンジン
target_position ベースのポジション調整 (ロングのみ: 0.0 ~ 1.0)
"""
import logging
from datetime import datetime, timezone

from src.config import (
    INITIAL_BALANCE, TOTAL_COST_RATE, USD_JPY_RATE,
    CIRCUIT_BREAKER_THRESHOLD, POSITION_CHANGE_THRESHOLD,
)
from src.database import (
    get_bot_state, update_bot_state, save_trade,
    save_balance_snapshot, get_positions,
)

logger = logging.getLogger(__name__)

# サーキットブレーカー復帰用ヒステリシス: 損失率がこの値まで戻れば再稼働
RECOVERY_LOSS_RATE = CIRCUIT_BREAKER_THRESHOLD * 0.5  # 例: 20% → 10%まで回復で復帰


class Simulator:
    """
    仮想約定エンジン (target_position ベース)。

    - 各botの仮想残高・ポジションを管理
    - target_position と current_position の差分でトレード実行
    - 循環ブレーカー判定は全銘柄の時価評価で行う (偽陽性防止)
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

        # ポジション: {symbol: quantity (coin count)}
        positions = get_positions(self.bot_name)
        self.quantities = {}
        for symbol, data in positions.items():
            self.quantities[symbol] = data["position"]

    def apply_signal(self, symbol: str, signal: dict, current_price: float,
                     all_prices: dict = None) -> dict:
        """
        target_position に基づいてポジション調整する。

        Args:
            symbol: 対象銘柄ペア
            signal: {"target_position": 0.0~1.0, "confidence": float, "reason": str}
            current_price: 対象銘柄の現在価格 (USD建て)
            all_prices: 全銘柄の現在価格 dict {symbol: price_usd}
                       循環ブレーカー判定と total_asset 計算に使用。
                       None の場合は current_price のみで計算 (後方互換)。

        Returns:
            dict: 取引結果
        """
        # 全銘柄価格が渡されていなければ、少なくとも自銘柄は含める
        prices_dict = dict(all_prices) if all_prices else {}
        prices_dict[symbol] = current_price

        # サーキットブレーカー復帰判定 (非アクティブ時)
        if not self.is_active:
            if self._check_recovery(prices_dict):
                logger.info(f"[{self.bot_name}] ✅ 損失率回復によりサーキットブレーカー解除")
                self.is_active = True
                update_bot_state(self.bot_name, self.balance, is_active=True)
            else:
                return {"executed": False, "reason": "サーキットブレーカーにより停止中"}

        # USD→JPY変換
        price_jpy = current_price * USD_JPY_RATE

        target_pos = signal.get("target_position", 0.0)
        confidence = signal.get("confidence", 0.0)
        reason = signal.get("reason", "")

        # 現在のポジション比率 (全銘柄を考慮した total_asset で算出)
        total_asset = self._total_asset_jpy(prices_dict)
        current_qty = self.quantities.get(symbol, 0.0)
        current_value = current_qty * price_jpy
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
                symbol, price_jpy, delta, total_asset,
                target_pos, current_pos, confidence, now, reason
            )
        else:
            result = self._decrease_position(
                symbol, price_jpy, abs(delta), total_asset,
                target_pos, current_pos, confidence, now, reason
            )

        # サーキットブレーカー判定 (取引後、全銘柄評価で)
        if not self._check_circuit_breaker_jpy(prices_dict):
            self.is_active = False
            update_bot_state(self.bot_name, self.balance, is_active=False)

        return result

    def _increase_position(self, symbol, price_jpy, delta, total_asset,
                           target_pos, prev_pos, confidence, timestamp, reason):
        """ポジションを増やす (買い)。price_jpyはJPY建て。"""
        # 購入金額(円) = total_asset × delta
        buy_amount = total_asset * delta

        if buy_amount > self.balance:
            buy_amount = self.balance  # 残高上限

        if buy_amount <= 0:
            return {"executed": False, "reason": "残高不足"}

        effective_price = price_jpy * (1 + TOTAL_COST_RATE)
        quantity = buy_amount / effective_price

        self.balance -= buy_amount
        self.quantities[symbol] = self.quantities.get(symbol, 0.0) + quantity

        save_trade(
            timestamp=timestamp, bot_name=self.bot_name, symbol=symbol,
            action="BUY", price=price_jpy, effective_price=effective_price,
            quantity=quantity, balance=self.balance,
            position=self.quantities[symbol],
            target_position=target_pos, prev_position=prev_pos,
            confidence=confidence, note=reason,
        )
        update_bot_state(self.bot_name, self.balance)

        logger.info(
            f"[{self.bot_name}] BUY {symbol}: "
            f"pos {prev_pos:.2f}→{target_pos:.2f}, qty={quantity:.6f}, "
            f"残高=¥{self.balance:,.0f}"
        )
        return {
            "executed": True, "action": "BUY", "symbol": symbol,
            "quantity": quantity, "price": price_jpy,
            "effective_price": effective_price,
            "balance": self.balance,
            "prev_pos": prev_pos, "target_pos": target_pos,
        }

    def _decrease_position(self, symbol, price_jpy, delta, total_asset,
                           target_pos, prev_pos, confidence, timestamp, reason):
        """ポジションを減らす (売り)。price_jpyはJPY建て。"""
        current_qty = self.quantities.get(symbol, 0.0)
        if current_qty <= 0:
            return {"executed": False, "reason": f"{symbol}のポジションなし"}

        # 売却数量 = (delta / prev_pos) × current_qty (比率分だけ売却)
        if prev_pos > 0:
            sell_ratio = min(1.0, delta / prev_pos)
        else:
            sell_ratio = 1.0

        sell_quantity = current_qty * sell_ratio

        effective_price = price_jpy * (1 - TOTAL_COST_RATE)
        sale_amount = sell_quantity * effective_price

        self.balance += sale_amount
        self.quantities[symbol] = current_qty - sell_quantity

        profit_loss = sell_quantity * (effective_price - price_jpy)

        save_trade(
            timestamp=timestamp, bot_name=self.bot_name, symbol=symbol,
            action="SELL", price=price_jpy, effective_price=effective_price,
            quantity=sell_quantity, balance=self.balance,
            position=self.quantities[symbol],
            target_position=target_pos, prev_position=prev_pos,
            profit_loss=profit_loss, confidence=confidence, note=reason,
        )
        update_bot_state(self.bot_name, self.balance)

        logger.info(
            f"[{self.bot_name}] SELL {symbol}: "
            f"pos {prev_pos:.2f}→{target_pos:.2f}, qty={sell_quantity:.6f}, "
            f"残高=¥{self.balance:,.0f}"
        )
        return {
            "executed": True, "action": "SELL", "symbol": symbol,
            "quantity": sell_quantity, "price": price_jpy,
            "effective_price": effective_price,
            "balance": self.balance, "profit_loss": profit_loss,
            "prev_pos": prev_pos, "target_pos": target_pos,
        }

    def _total_asset_jpy(self, current_prices_usd: dict) -> float:
        """総資産(円)を計算する。current_prices_usdは全銘柄のUSD価格 dict。"""
        position_value = 0.0
        for sym, qty in self.quantities.items():
            if qty <= 0:
                continue
            price_usd = current_prices_usd.get(sym)
            if price_usd is None or price_usd <= 0:
                # 価格が取れない銘柄は警告 (ポジション評価不能 = 循環ブレーカー誤作動の元)
                logger.warning(
                    f"[{self.bot_name}] {sym} の価格なし → total_asset評価から除外 "
                    f"(qty={qty:.6f}). 循環ブレーカー判定が不正確になる可能性"
                )
                continue
            position_value += qty * price_usd * USD_JPY_RATE
        return self.balance + position_value

    def _check_circuit_breaker_jpy(self, current_prices_usd: dict) -> bool:
        """サーキットブレーカー判定。True=継続, False=発動 (停止)。"""
        total = self._total_asset_jpy(current_prices_usd)
        loss_rate = (INITIAL_BALANCE - total) / INITIAL_BALANCE
        if loss_rate >= CIRCUIT_BREAKER_THRESHOLD:
            logger.warning(
                f"[{self.bot_name}] ⚠️ サーキットブレーカー発動！ "
                f"総資産: ¥{total:,.0f} (損失率: {loss_rate:.1%})"
            )
            return False
        return True

    def _check_recovery(self, current_prices_usd: dict) -> bool:
        """停止中botが復帰可能か判定。総資産が回復閾値以上なら True。"""
        total = self._total_asset_jpy(current_prices_usd)
        loss_rate = (INITIAL_BALANCE - total) / INITIAL_BALANCE
        return loss_rate < RECOVERY_LOSS_RATE

    def save_snapshot(self, current_prices: dict, trade_count: int = 0):
        """残高スナップショット(円)を保存する。current_pricesはUSD建て全銘柄dict。"""
        position_value = 0.0
        for sym, qty in self.quantities.items():
            if qty <= 0:
                continue
            price = current_prices.get(sym)
            if price is None or price <= 0:
                continue
            position_value += qty * price * USD_JPY_RATE
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
