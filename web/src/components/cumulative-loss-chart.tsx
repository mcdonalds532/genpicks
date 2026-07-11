"use client";

import { useRef, useState } from "react";
import type { LossPoint } from "@/lib/backtest";

// Cumulative mean log loss over the held-out test seasons: two lines
// (model in slot-1 blue, bookmaker closing in slot-2 aqua — the palette
// validated in globals.css) against the 0.693 coin-flip baseline. The two
// series converge at the right edge, so identity rides the legend and the
// crosshair tooltip rather than colliding end-labels; the aqua slot sits
// under 3:1 on the light surface, and the always-visible legend text plus
// the table twin on the page are its relief channel.

const W = 640;
const H = 300;
const M = { top: 14, right: 16, bottom: 30, left: 48 };
const IW = W - M.left - M.right;
const IH = H - M.top - M.bottom;
const COIN_FLIP = Math.log(2);

const fmt = (v: number) => v.toFixed(4);
const fmtDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-AU", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

export function CumulativeLossChart({
  points,
  seasons,
}: {
  points: LossPoint[];
  seasons: { at: number; label: string }[];
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [active, setActive] = useState<number | null>(null);

  const values = points.flatMap((p) => [p.model, p.market]);
  const step = 0.02;
  const lo = Math.floor(Math.min(...values, COIN_FLIP) / step) * step;
  const hi = Math.ceil(Math.max(...values, COIN_FLIP) / step) * step;
  const x = (i: number) => M.left + (i / (points.length - 1)) * IW;
  const y = (v: number) => M.top + ((hi - v) / (hi - lo)) * IH;

  const yTicks: number[] = [];
  for (let t = lo; t <= hi + 1e-9; t += step) yTicks.push(Math.round(t * 100) / 100);

  const toPath = (get: (p: LossPoint) => number) =>
    points.map((p, i) => `${x(i).toFixed(1)},${y(get(p)).toFixed(1)}`).join(" ");

  const indexFromPointer = (clientX: number) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const px = ((clientX - rect.left) / rect.width) * W;
    const i = Math.round(((px - M.left) / IW) * (points.length - 1));
    return Math.min(Math.max(i, 0), points.length - 1);
  };

  const move = (by: number) =>
    setActive((a) => Math.min(Math.max((a ?? points.length - 1) + by, 0), points.length - 1));

  const last = points[points.length - 1];
  const a = active === null ? null : points[active];

  return (
    <div className="relative">
      <div className="mb-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-2">
        <span>
          <span aria-hidden className="mr-1.5 inline-block h-0.5 w-4 rounded bg-series-model align-middle" />
          Model
        </span>
        <span>
          <span aria-hidden className="mr-1.5 inline-block h-0.5 w-4 rounded bg-series-market align-middle" />
          Bookmaker closing odds
        </span>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="block w-full touch-none select-none"
        role="img"
        aria-label={`Cumulative mean log loss across ${last.n} test matches: model finishes at ${fmt(last.model)}, bookmaker closing odds at ${fmt(last.market)}, both below the 0.693 coin-flip baseline. Full values in the data table below.`}
        tabIndex={0}
        onPointerMove={(e) => setActive(indexFromPointer(e.clientX))}
        onPointerLeave={() => setActive(null)}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") (e.preventDefault(), move(-1));
          if (e.key === "ArrowRight") (e.preventDefault(), move(1));
          if (e.key === "Escape") setActive(null);
        }}
        onFocus={() => setActive((v) => v ?? points.length - 1)}
        onBlur={() => setActive(null)}
      >
        {yTicks.map((t) => (
          <g key={t}>
            <line
              x1={M.left}
              x2={W - M.right}
              y1={y(t)}
              y2={y(t)}
              className="stroke-hairline"
              strokeWidth={1}
            />
            <text
              x={M.left - 6}
              y={y(t)}
              textAnchor="end"
              dominantBaseline="central"
              className="fill-muted text-[10px] tabular-nums"
            >
              {t.toFixed(2)}
            </text>
          </g>
        ))}
        {seasons.map((s) => (
          <g key={s.label}>
            <line
              x1={x(s.at)}
              x2={x(s.at)}
              y1={H - M.bottom}
              y2={H - M.bottom + 4}
              className="stroke-muted"
              strokeWidth={1}
            />
            <text
              x={x(s.at)}
              y={H - M.bottom + 16}
              textAnchor={s.at === 0 ? "start" : "middle"}
              className="fill-muted text-[10px]"
            >
              {s.label}
            </text>
          </g>
        ))}
        <line
          x1={M.left}
          x2={W - M.right}
          y1={y(COIN_FLIP)}
          y2={y(COIN_FLIP)}
          className="stroke-muted"
          strokeWidth={1}
        />
        <text
          x={W - M.right}
          y={y(COIN_FLIP) - 5}
          textAnchor="end"
          className="fill-muted text-[10px]"
        >
          coin flip 0.693
        </text>
        <polyline
          points={toPath((p) => p.market)}
          fill="none"
          className="stroke-series-market"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        <polyline
          points={toPath((p) => p.model)}
          fill="none"
          className="stroke-series-model"
          strokeWidth={2}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {a !== null && active !== null && (
          <g>
            <line
              x1={x(active)}
              x2={x(active)}
              y1={M.top}
              y2={H - M.bottom}
              className="stroke-muted"
              strokeWidth={1}
            />
            <circle cx={x(active)} cy={y(a.model)} r={4} className="fill-series-model stroke-surface" strokeWidth={2} />
            <circle cx={x(active)} cy={y(a.market)} r={4} className="fill-series-market stroke-surface" strokeWidth={2} />
          </g>
        )}
      </svg>
      {a !== null && active !== null && (
        <div
          className="pointer-events-none absolute top-8 z-10 -translate-x-1/2 rounded-md border border-hairline bg-surface px-3 py-2 text-xs shadow-sm"
          style={{
            left: `${Math.min(Math.max((x(active) / W) * 100, 14), 86)}%`,
          }}
        >
          <p className="mb-1 whitespace-nowrap text-muted">
            {fmtDate(a.date)} · after {a.n} matches
          </p>
          <p className="whitespace-nowrap">
            <span aria-hidden className="mr-1.5 inline-block h-0.5 w-3 rounded bg-series-model align-middle" />
            <span className="font-medium tabular-nums">{fmt(a.model)}</span>{" "}
            <span className="text-ink-2">model</span>
          </p>
          <p className="whitespace-nowrap">
            <span aria-hidden className="mr-1.5 inline-block h-0.5 w-3 rounded bg-series-market align-middle" />
            <span className="font-medium tabular-nums">{fmt(a.market)}</span>{" "}
            <span className="text-ink-2">bookmakers</span>
          </p>
        </div>
      )}
    </div>
  );
}
