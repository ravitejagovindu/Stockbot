import { apiClient } from "./client";

export interface HealthResponse {
  status: string;
  authorized: boolean;
  sha_locked: boolean;
  tree_clean: boolean;
  authorized_sha: string | null;
  current_sha?: string | null;
  last_pipeline_run: any;
}

export interface RegimeState {
  eval_date: string;
  kill_switch_active: boolean;
  nifty_close: number;
  nifty_sma200: number;
  nifty_sma50: number;
  vix_close: number;
  trigger_reason: string;
  reentry_consecutive_count: number;
  reentry_sessions_required: number;
  reentry_progress_pct: number | null;
  nifty_distance_to_sma200_pct: number;
  nifty_distance_to_sma50_pct: number;
  vix_distance_to_trigger_pct: number;
  vix_distance_to_reentry_pct: number;
}

export interface LedgerSummary {
  live_equity: number;
  total_deposits: number;
  total_withdrawals: number;
  total_realized_pnl: number;
  fallback_used: boolean;
}

export interface LedgerRequest {
  amount: number;
  notes?: string;
}

export const fetchLedgerSummary = async (): Promise<LedgerSummary> => {
  const { data } = await apiClient.get("/ledger/summary");
  return data;
};

export const depositFunds = async (req: LedgerRequest) => {
  const { data } = await apiClient.post("/ledger/deposit", req);
  return data;
};

export const withdrawFunds = async (req: LedgerRequest) => {
  const { data } = await apiClient.post("/ledger/withdraw", req);
  return data;
};

export interface WatchlistResponse {
  run_date: string;
  approved_count: number;
  blocked_count: number;
  approved: any[];
  blocked: any[];
}

export interface PortfolioSummary {
  open_positions?: number;
  max_positions?: number;
  total_equity?: number;
  account_equity?: number;
  cash?: number;
  invested_capital?: number;
  unrealized_pnl?: number;
  total_realized_pnl?: number;
  total_risk_pct?: number;
  max_risk_pct?: number;
  max_sector_pct?: number;
  peak_equity?: number;
  current_drawdown_pct?: number;
  capital_deployed_pct?: number;
  pending_manual_exits?: string[] | any[];
  earnings_alerts?: string[] | any[];
}

export interface Position {
  id: number;
  symbol: string;
  shares: number;
  entry_price: number;
  current_price: number;
  initial_stop_loss: number;
  live_stop_loss: number;
  days_held: number;
  earnings_alert: boolean;
  sector?: string;
  entry_date?: string;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  active_stop?: string;
}

export interface PortfolioResponse {
  positions: Position[];
  summary: PortfolioSummary;
  sector_performance?: any[];
}

export interface AnalyticsSummary {
  total_trades?: number;
  win_rate?: number;
  avg_win?: number;
  avg_loss?: number;
  expectancy?: number;
  projected_rr_avg?: number;
  avg_projected_rr?: number;
  realized_rr_avg?: number;
  avg_realized_rr?: number;
  decay_ratio?: number;
  decay_signal?: "HEALTHY" | "MONITOR" | "WARNING" | "CRITICAL" | string;
}

export interface AnalyticsResponse {
  summary: AnalyticsSummary;
  trades: any[];
}

export interface ClosePositionRequest {
  position_id: number;
  exit_price: number;
  exit_date: string;
  exit_reason: string;
}

export const fetchHealth = async (): Promise<HealthResponse> => {
  const { data } = await apiClient.get("/health");
  return data;
};

export const fetchRegime = async (): Promise<RegimeState> => {
  const { data } = await apiClient.get("/regime");
  return data;
};

export const fetchWatchlist = async (date?: string): Promise<WatchlistResponse> => {
  const url = date ? `/watchlist?run_date=${date}` : "/watchlist";
  const { data } = await apiClient.get(url);
  return data;
};

export const fetchPortfolio = async (): Promise<PortfolioResponse> => {
  const { data } = await apiClient.get("/portfolio");
  return data;
};

export const fetchAnalytics = async (limit: number = 200): Promise<AnalyticsResponse> => {
  const { data } = await apiClient.get(`/analytics?limit=${limit}`);
  return data;
};

export const closePosition = async (req: ClosePositionRequest) => {
  const { data } = await apiClient.post("/positions/close", req);
  return data;
};
