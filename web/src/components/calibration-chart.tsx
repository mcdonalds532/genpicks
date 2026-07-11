"use client";

import { useState } from "react";
import type { CalibrationBin } from "@/lib/backtest";

// Reliability plot: mean predicted home-win probability per bin against the
// observed rate, with the y = x diagonal as "perfectly calibrated". One
// series, so no legend box — the card title names it. Every dot carries an
// oversized invisible hit circle (the 24px rule) and is keyboard-focusable
// with the same readout as hover; the full numbers live in the table twin.

const S = 320;
const M = { top: 12, right: 14, bottom: 40, left: 44 };
const IW = S - M.left - M.right;
const IH = S - M.top - M.bottom;
const TICKS = [0, 0.25, 0.5, 0.75, 1];

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

export function CalibrationChart({ bins }: { bins: CalibrationBin[] }) {
  const [active, setActive] = useState<number | null>(null);

  const x = (v: number) => M.left + v * IW;
  const y = (v: number) => M.top + (1 - v) * IH;
  const a = active === null ? null : bins[active];

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${S} ${S}`}
        className="mx-auto block w-full max-w-90 touch-none select-none"
        role="img"
        aria-label={`Calibration of predicted home-win probabilities across ${bins.length} bins; dots near the diagonal mean predicted probabilities match observed win rates. Full values in the data table below.`}
      >
        {TICKS.map((t) => (
          <g key={t}>
            <line
              x1={x(t)}
              x2={x(t)}
              y1={M.top}
              y2={S - M.bottom}
              className="stroke-hairline"
              strokeWidth={1}
            />
            <line
              x1={M.left}
              x2={S - M.right}
              y1={y(t)}
              y2={y(t)}
              className="stroke-hairline"
              strokeWidth={1}
            />
            <text
              x={x(t)}
              y={S - M.bottom + 14}
              textAnchor="middle"
              className="fill-muted text-[10px] tabular-nums"
            >
              {t}
            </text>
            <text
              x={M.left - 6}
              y={y(t)}
              textAnchor="end"
              dominantBaseline="central"
              className="fill-muted text-[10px] tabular-nums"
            >
              {t}
            </text>
          </g>
        ))}
        <text
          x={M.left + IW / 2}
          y={S - 6}
          textAnchor="middle"
          className="fill-muted text-[10px]"
        >
          predicted home-win probability
        </text>
        <text
          x={12}
          y={M.top + IH / 2}
          textAnchor="middle"
          transform={`rotate(-90 12 ${M.top + IH / 2})`}
          className="fill-muted text-[10px]"
        >
          actual home-win rate
        </text>
        <line
          x1={x(0)}
          y1={y(0)}
          x2={x(1)}
          y2={y(1)}
          className="stroke-muted"
          strokeWidth={1}
        />
        <text
          x={x(0.7)}
          y={y(0.7) + 26}
          textAnchor="middle"
          transform={`rotate(-45 ${x(0.7)} ${y(0.7) + 26})`}
          className="fill-muted text-[10px]"
        >
          perfectly calibrated
        </text>
        {bins.map((b, i) => (
          <g
            key={b.lo}
            tabIndex={0}
            role="img"
            aria-label={`Bin ${b.lo.toFixed(1)} to ${b.hi.toFixed(1)}: ${b.n} matches, predicted ${pct(b.predicted)}, actual ${pct(b.actual)}`}
            className="cursor-default outline-none"
            onPointerEnter={() => setActive(i)}
            onPointerLeave={() => setActive(null)}
            onFocus={() => setActive(i)}
            onBlur={() => setActive(null)}
          >
            <circle cx={x(b.predicted)} cy={y(b.actual)} r={14} fill="transparent" />
            <circle
              cx={x(b.predicted)}
              cy={y(b.actual)}
              r={active === i ? 6 : 5}
              className="fill-series-model stroke-surface"
              strokeWidth={2}
            />
          </g>
        ))}
      </svg>
      {a !== null && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-full rounded-md border border-hairline bg-surface px-3 py-2 text-xs shadow-sm"
          style={{
            left: `${Math.min(Math.max((x(a.predicted) / S) * 100, 22), 78)}%`,
            top: `${(y(a.actual) / S) * 100 - 4}%`,
          }}
        >
          <p className="mb-1 whitespace-nowrap text-muted">
            predictions {a.lo.toFixed(1)}–{a.hi.toFixed(1)} · {a.n} matches
          </p>
          <p className="whitespace-nowrap">
            <span className="font-medium tabular-nums">{pct(a.actual)}</span>{" "}
            <span className="text-ink-2">actual vs</span>{" "}
            <span className="font-medium tabular-nums">{pct(a.predicted)}</span>{" "}
            <span className="text-ink-2">predicted</span>
          </p>
        </div>
      )}
    </div>
  );
}
