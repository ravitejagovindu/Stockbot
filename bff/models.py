"""Response models of the StockBot Paper API, version 1: the pydantic form of docs/android/contract (openapi.yaml, CONTRACT.md).

The contract is the single source: tests/bff/test_contract_models.py validates every example file against these models, so a drift in either shows up at once.
Field names are the JSON keys (camelCase). Money is integer paise. ``extra='forbid'`` makes an unknown key an error, so the BFF can never send a field the contract does not list.
"""
from __future__ import annotations

from datetime import date
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

API_VERSION = "1"
TS_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30$"

ExitReason = Literal["STOP_HIT", "GAP_THROUGH_STOP", "OTHER"]
BlockReason = Literal["SECTOR_CAP", "CASH", "RISK_CAP", "OTHER"]
Side = Literal["BUY", "SELL"]
ErrorCode = Literal["UNAUTHORIZED", "NOT_READY", "SERVER_ERROR"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Envelope(Strict):
    apiVersion: Literal["1"]
    dataAsOf: date
    expectedAsOf: date
    generatedAt: str = Field(pattern=TS_PATTERN)


# ------------------------------------------------------------------------------------------------------------------------------ errors
class ErrorBody(Strict):
    code: ErrorCode
    message: str


class ErrorResponse(Strict):
    apiVersion: Literal["1"]
    error: ErrorBody


# ------------------------------------------------------------------------------------------------------------------------------ health
class Health(Envelope):
    status: Literal["ok", "not_ready"]
    serverTime: str = Field(pattern=TS_PATTERN)
    latestSealedDate: Optional[date]


# ------------------------------------------------------------------------------------------------------------------------------ today
class Ticket(Strict):
    symbol: str
    sector: Optional[str]
    shares: int = Field(ge=1)
    entryReferencePaise: int
    stopPaise: int
    riskPaise: int


class BlockedItem(Strict):
    symbol: str
    sector: Optional[str]
    reason: BlockReason


class PendingFill(Strict):
    symbol: str
    side: Side
    shares: int = Field(ge=1)
    note: str


class Today(Envelope):
    isSignalDay: bool
    riskPerTradePct: float
    tickets: List[Ticket]
    blocked: List[BlockedItem]
    pendingFills: List[PendingFill]
    nextSignalRule: str


# ------------------------------------------------------------------------------------------------------------------------------ account
class AccountSummary(Strict):
    startDate: date
    startingCapitalPaise: int
    equityPaise: int
    cashPaise: int
    returnPct: float
    niftyReturnPct: float
    drawdownNowPct: float = Field(ge=0)
    drawdownWorstPct: float = Field(ge=0)
    closedTrades: int = Field(ge=0)


class CurvePoint(Strict):
    date: date
    accountPaise: int
    niftyPaise: int


class Marks(Strict):
    drawdownReviewPct: float
    closedTradesTarget: int
    verdict: str


class Account(Envelope):
    summary: AccountSummary
    curve: List[CurvePoint]
    marks: Marks


# ------------------------------------------------------------------------------------------------------------------------------ positions
class Position(Strict):
    symbol: str
    shares: int = Field(ge=1)
    entryDate: date
    entryPricePaise: int
    stopPaise: int
    lastClosePaise: int
    unrealisedPnlPaise: int
    corporateActionFlag: bool = False


class Positions(Envelope):
    cashPaise: int
    positions: List[Position]


# ------------------------------------------------------------------------------------------------------------------------------ trades
class ClosedTrade(Strict):
    symbol: str
    entryDate: date
    exitDate: date
    exitReason: ExitReason
    netPnlPaise: int
    netR: float
    corporateActionFlag: bool = False


class TradeStats(Strict):
    tradeCount: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    winRatePct: Optional[float]
    profitFactor: Optional[float]
    excludedFromStats: int = Field(default=0, ge=0)


class Trades(Envelope):
    trades: List[ClosedTrade]
    stats: TradeStats
