import { Suspense } from "react";
import fs from "fs";
import path from "path";

// Types based on python export script
type BotPosition = {
  symbol: string;
  quantity: number;
  price_usd: number;
  value_jpy_fixed: number;
};

type BotData = {
  name: string;
  display_name: string;
  status: "active" | "stopped";
  total_jpy_fixed: number;
  pnl_jpy: number;
  pnl_pct: number;
  trade_count_today: number;
  positions: BotPosition[];
};

type TradeData = {
  timestamp: string;
  bot: string;
  action: string;
  symbol: string;
  price: number;
  quantity: number;
  icon: string;
};

type DashboardData = {
  metadata: {
    updated_at: string;
    usd_jpy_real: number;
    usd_jpy_fixed: number;
  };
  summary: {
    total_asset_fixed: number;
    total_asset_real: number;
    total_pnl: number;
    total_pnl_pct: number;
    active_bots: number;
    total_bots: number;
  };
  bots: BotData[];
  recent_trades: TradeData[];
};

// Data Fetching logic
async function getDashboardData(): Promise<DashboardData | null> {
  try {
    // In production, fetch from GitHub Raw User Content
    if (process.env.NODE_ENV === "production") {
      const res = await fetch("https://raw.githubusercontent.com/OjiTakuya/crypto-bot/main/docs/dashboard.json", {
        next: { revalidate: 3600 },
      });
      if (!res.ok) throw new Error("Failed to fetch from GitHub");
      return res.json();
    }

    // In development, read from the local public folder using fs to avoid Next.js SSR fetch issues
    const filePath = path.join(process.cwd(), "public", "docs", "dashboard.json");
    if (fs.existsSync(filePath)) {
      const fileContents = fs.readFileSync(filePath, "utf8");
      return JSON.parse(fileContents);
    } else {
      console.warn(`Local dashboard data not found at ${filePath}`);
      return null;
    }
  } catch (error) {
    console.error("Error fetching dashboard data:", error);
    return null;
  }
}

// Formatters
const formatJPY = (val: number) =>
  new Intl.NumberFormat('ja-JP', { style: 'currency', currency: 'JPY', maximumFractionDigits: 0 }).format(val);

const formatPct = (val: number) =>
  new Intl.NumberFormat('ja-JP', { style: 'percent', minimumFractionDigits: 2 }).format(val / 100);

export default async function DashboardPage() {
  const data = await getDashboardData();

  if (!data) {
    return (
      <main className="min-h-screen p-phi-2 flex items-center justify-center">
        <div className="glass-card p-phi-2 text-center">
          <h1 className="text-xl text-brand-danger mb-phi-1">Error Loading Data</h1>
          <p className="text-sm opacity-70">Could not fetch dashboard JSON.</p>
        </div>
      </main>
    );
  }

  const { summary, metadata, bots, recent_trades } = data;
  const isProfit = summary.total_pnl >= 0;

  return (
    <main className="min-h-screen p-phi-1 md:p-phi-2 max-w-7xl mx-auto space-y-phi-3">
      {/* HEADER SECTION */}
      <header className="space-y-phi-half">
        <h1 className="text-xl font-bold tracking-tight opacity-90">Crypto Bot Dashboard</h1>
        <p className="text-sm opacity-50 font-mono">
          Last Updated: {new Date(metadata.updated_at).toLocaleString('ja-JP')}
        </p>
      </header>

      {/* HERO SECTION: TOTAL ASSET */}
      <section className="glass-card p-phi-2 relative overflow-hidden">
        <div className="absolute top-0 right-0 w-64 h-64 bg-brand-primary opacity-10 blur-[100px] rounded-full -translate-y-1/2 translate-x-1/2" />

        <p className="text-sm uppercase tracking-widest opacity-70 mb-phi-1 font-semibold">Total Asset Value</p>
        <h2 className="text-3xl md:text-5xl font-mono font-bold tracking-tighter">
          {formatJPY(summary.total_asset_fixed)}
        </h2>

        <div className="mt-phi-1 flex items-end gap-phi-1">
          <span className={`text-xl font-mono font-bold ${isProfit ? 'text-brand-success' : 'text-brand-danger'}`}>
            {isProfit ? '+' : ''}{formatJPY(summary.total_pnl)}
          </span>
          <span className={`text-base font-mono ${isProfit ? 'text-brand-success' : 'text-brand-danger'} opacity-80 bg-opacity-10 px-2 py-1 rounded-md`}>
            {isProfit ? '▲' : '▼'} {formatPct(summary.total_pnl_pct * 100)}
          </span>
        </div>

        <div className="mt-phi-2 pt-phi-1 border-t border-white/10 flex gap-phi-2 text-sm opacity-60">
          <p>Active Bots: <strong className="text-white">{summary.active_bots} / {summary.total_bots}</strong></p>
          <p>Fixed Rate: <strong className="text-white">1 USD = {metadata.usd_jpy_fixed} JPY</strong></p>
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-phi-2">
        {/* BOT CARDS SECTION (Takes up 2/3 of grid on large screens) */}
        <section className="lg:col-span-2 space-y-phi-1">
          <h3 className="text-base font-semibold uppercase tracking-wider opacity-80 border-b border-white/10 pb-2 mb-phi-1">
            Bot Performance
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-phi-1">
            {bots.map((bot) => {
              const botProfit = bot.pnl_jpy >= 0;
              return (
                <div key={bot.name} className="glass-card p-phi-1 hover:border-brand-primary/30 transition-colors">
                  <div className="flex justify-between items-start mb-phi-half">
                    <h4 className="font-bold text-lg opacity-90">{bot.display_name}</h4>
                    <span className={`text-xs px-2 py-1 rounded-full ${bot.status === 'active' ? 'bg-brand-success/20 text-brand-success' : 'bg-white/10 text-white/50'}`}>
                      {bot.status}
                    </span>
                  </div>

                  <div className="space-y-1 mb-phi-1">
                    <p className="text-xl font-mono">{formatJPY(bot.total_jpy_fixed)}</p>
                    <p className={`text-sm font-mono ${botProfit ? 'text-brand-success' : 'text-brand-danger'}`}>
                      {botProfit ? '+' : ''}{formatJPY(bot.pnl_jpy)} ({formatPct(bot.pnl_pct * 100)})
                    </p>
                  </div>

                  {bot.positions.length > 0 ? (
                    <div className="text-xs opacity-70">
                      <p className="mb-1">Active Positions:</p>
                      <div className="flex gap-2 flex-wrap">
                        {bot.positions.map(p => (
                          <span key={p.symbol} className="bg-white/5 px-2 py-1 rounded border border-white/10">
                            {p.symbol} x {p.quantity}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs opacity-40 italic">No active positions</p>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        {/* RECENT TRADES SECTION */}
        <section className="space-y-phi-1">
          <h3 className="text-base font-semibold uppercase tracking-wider opacity-80 border-b border-white/10 pb-2 mb-phi-1">
            Recent Trades
          </h3>
          <div className="glass-card max-h-[600px] overflow-y-auto no-scrollbar">
            {recent_trades.length === 0 ? (
              <p className="p-phi-1 text-center opacity-50 text-sm">No trades in the last 24h</p>
            ) : (
              <ul className=" divide-y divide-white/5">
                {recent_trades.map((trade, idx) => (
                  <li key={idx} className="p-phi-1 text-sm flex gap-3 items-center hover:bg-white/5 transition-colors">
                    <div className="text-xl">{trade.icon}</div>
                    <div className="flex-1">
                      <div className="flex justify-between">
                        <span className="font-bold text-brand-primary">{trade.bot}</span>
                        <span className="opacity-50 text-xs">
                          {new Date(trade.timestamp).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      </div>
                      <div className="flex justify-between opacity-80 mt-1">
                        <span>{trade.action} {trade.symbol}</span>
                        <span className="font-mono">{trade.quantity} @ ${trade.price}</span>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
