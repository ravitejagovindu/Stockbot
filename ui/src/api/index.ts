import { apiClient } from "./client";

export interface HealthResponse {
  status: string;
  authorized: boolean;
  sha_locked: boolean;
  tree_clean: boolean;
  authorized_sha: string | null;
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

export interface PortfolioResponse {
  positions: any[];
  summary: any;
}

export interface AnalyticsResponse {
  summary: any;
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

export interface RecordPartialExitRequest {
  position_id: number;
  exit_price: number;
  shares_sold: number;
  exit_date: string;
}

export const recordPartialClose = async (req: RecordPartialExitRequest) => {
  const { data } = await apiClient.post("/positions/partial_close", req);
  return data;
};
