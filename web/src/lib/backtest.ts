// Pure math over the committed backtest export (web/src/data/backtest.json).
// Everything here runs in the server component at render time; the chart
// components receive small precomputed arrays.

export type BacktestMatch = {
  date: string;
  season: number;
  home: string | null;
  away: string | null;
  p_model: number;
  p_market: number | null;
  home_win: number;
};

export type Backtest = {
  model_version: string;
  splits: { train: number[]; val: number[]; test: number[] };
  matches: BacktestMatch[];
};

export const COIN_FLIP = Math.log(2); // log loss of always predicting 50%

const clamp = (p: number) => Math.min(Math.max(p, 1e-9), 1 - 1e-9);

export const logLoss = (p: number, y: number) => {
  const q = clamp(p);
  return -(y * Math.log(q) + (1 - y) * Math.log(1 - q));
};

export type LossPoint = {
  date: string;
  n: number; // matches settled so far
  model: number; // cumulative mean log loss
  market: number;
};

// Cumulative mean log loss over matches that have a market price, skipping
// the first `burnIn` points where a handful of matches swings the mean too
// wildly to read.
export function cumulativeLoss(
  matches: BacktestMatch[],
  burnIn = 20,
): LossPoint[] {
  const priced = matches.filter((m) => m.p_market !== null);
  const points: LossPoint[] = [];
  let sumModel = 0;
  let sumMarket = 0;
  priced.forEach((m, i) => {
    sumModel += logLoss(m.p_model, m.home_win);
    sumMarket += logLoss(m.p_market as number, m.home_win);
    if (i + 1 >= burnIn) {
      points.push({
        date: m.date,
        n: i + 1,
        model: sumModel / (i + 1),
        market: sumMarket / (i + 1),
      });
    }
  });
  return points;
}

// Index of each season's first point, for x-axis labels.
export function seasonStarts(
  matches: BacktestMatch[],
  points: LossPoint[],
): { at: number; label: string }[] {
  const firstDate = new Map<number, string>();
  for (const m of matches) {
    if (!firstDate.has(m.season)) firstDate.set(m.season, m.date);
  }
  const starts: { at: number; label: string }[] = [];
  for (const [season, date] of firstDate) {
    const at = points.findIndex((p) => p.date >= date);
    if (at >= 0) starts.push({ at, label: String(season) });
  }
  return starts;
}

export type CalibrationBin = {
  lo: number;
  hi: number;
  n: number;
  predicted: number; // mean model probability in the bin
  actual: number; // observed home-win rate in the bin
};

// Same binning rule as the training report: ten uniform bins, keep n >= 10.
export function calibrationBins(
  matches: BacktestMatch[],
  bins = 10,
  minN = 10,
): CalibrationBin[] {
  const out: CalibrationBin[] = [];
  for (let b = 0; b < bins; b++) {
    const lo = b / bins;
    const hi = (b + 1) / bins;
    const inBin = matches.filter(
      (m) => m.p_model >= lo && (b === bins - 1 ? m.p_model <= hi : m.p_model < hi),
    );
    if (inBin.length < minN) continue;
    out.push({
      lo,
      hi,
      n: inBin.length,
      predicted: inBin.reduce((s, m) => s + m.p_model, 0) / inBin.length,
      actual: inBin.reduce((s, m) => s + m.home_win, 0) / inBin.length,
    });
  }
  return out;
}

export type SeasonStats = {
  season: number;
  n: number;
  modelLoss: number;
  marketLoss: number;
  modelAccuracy: number;
  marketAccuracy: number;
};

export function perSeason(matches: BacktestMatch[]): SeasonStats[] {
  const seasons = [...new Set(matches.map((m) => m.season))].sort();
  return seasons.map((season) => {
    const ms = matches.filter((m) => m.season === season && m.p_market !== null);
    const n = ms.length;
    const mean = (f: (m: BacktestMatch) => number) =>
      ms.reduce((s, m) => s + f(m), 0) / n;
    return {
      season,
      n,
      modelLoss: mean((m) => logLoss(m.p_model, m.home_win)),
      marketLoss: mean((m) => logLoss(m.p_market as number, m.home_win)),
      modelAccuracy: mean((m) => Number(m.p_model > 0.5 === Boolean(m.home_win))),
      marketAccuracy: mean((m) =>
        Number((m.p_market as number) > 0.5 === Boolean(m.home_win)),
      ),
    };
  });
}
