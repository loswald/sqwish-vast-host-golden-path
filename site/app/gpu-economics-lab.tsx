'use client';

import { useEffect, useId, useMemo, useRef, useState } from 'react';
import {
  ArrowDownRight,
  ArrowUpRight,
  Asterisk,
  BadgePoundSterling,
  CircleDollarSign,
  CircleHelp,
  ExternalLink,
  FlaskConical,
  Gauge,
  Repeat2,
  RotateCcw,
  ServerCog,
  Sparkles,
  Undo2,
  Zap,
} from 'lucide-react';
import { Bar, BarChart, CartesianGrid, Cell, XAxis, YAxis } from 'recharts';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';

const SCAN_PUBLIC_EX_VAT = 1_666.65;
const USD_PER_GBP = 1.159 / 0.85655;
const GPU_HOURS = 4 * 30 * 24;
const STORAGE_USD_PER_GB_MONTH = 0.2;

type Assumptions = {
  ownerUse: number;
  idleFill: number;
  hostRate: number;
  discount: number;
  periods: number;
  storageGb: number;
};

type WebMcpTool = {
  name: string;
  title?: string;
  description: string;
  inputSchema: Record<string, unknown>;
  annotations?: { readOnlyHint?: boolean; untrustedContentHint?: boolean };
  execute(input: unknown): unknown | Promise<unknown>;
};

declare global {
  interface Document {
    readonly modelContext?: {
      registerTool(tool: WebMcpTool, options?: { signal?: AbortSignal }): void | Promise<void>;
    };
  }
}

const defaults: Assumptions = {
  ownerUse: 20,
  idleFill: 74.4,
  hostRate: 0.8,
  discount: 25,
  periods: 18,
  storageGb: 100,
};

const presets: Record<string, Pick<Assumptions, 'idleFill' | 'hostRate' | 'discount'>> = {
  Downside: { idleFill: 40, hostRate: 0.61, discount: 20 },
  Base: { idleFill: 74.4, hostRate: 0.8, discount: 25 },
  Upside: { idleFill: 90, hostRate: 0.9, discount: 30 },
};

const chartConfig = {
  value: { label: 'GBP', color: 'var(--chart-1)' },
} satisfies ChartConfig;

const money = new Intl.NumberFormat('en-GB', {
  style: 'currency',
  currency: 'GBP',
  maximumFractionDigits: 0,
});

function compute(a: Assumptions) {
  const ownerGpuHours = GPU_HOURS * (a.ownerUse / 100);
  const sellableGpuHours = GPU_HOURS - ownerGpuHours;
  const rentedGpuHours = sellableGpuHours * (a.idleFill / 100);
  const income = (rentedGpuHours * a.hostRate) / USD_PER_GBP;
  const scanCost = SCAN_PUBLIC_EX_VAT * (1 - a.discount / 100);
  const storage = (a.storageGb * STORAGE_USD_PER_GB_MONTH) / USD_PER_GBP;
  const effective = scanCost + storage - income;
  const maxIncome = (sellableGpuHours * a.hostRate) / USD_PER_GBP;
  const breakEvenFill = maxIncome > 0 ? ((scanCost + storage) / maxIncome) * 100 : Infinity;

  return {
    ownerGpuHours,
    rentedGpuHours,
    income,
    scanCost,
    storage,
    effective,
    termEffective: effective * a.periods,
    termScanCost: scanCost * a.periods,
    termIncome: income * a.periods,
    breakEvenFill,
    effectivePerOwnerHour: ownerGpuHours > 0 ? effective / ownerGpuHours : null,
  };
}

function Control({
  label,
  value,
  display,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  display: string;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  const id = useId();

  return (
    <div className="space-y-3 border-b border-border/70 pb-5 last:border-0 last:pb-0">
      <div className="flex items-baseline justify-between gap-4">
        <label htmlFor={id} className="text-sm font-medium text-foreground">
          {label}
        </label>
        <output className="font-mono text-sm font-semibold tabular-nums text-primary">
          {display}
        </output>
      </div>
      <input
        id={id}
        className="economics-slider"
        aria-label={label}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onInput={(event) => onChange(Number(event.currentTarget.value))}
        onChange={(event) => onChange(Number(event.currentTarget.value))}
      />
      <div className="flex justify-between font-mono text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
        <span>{min}</span>
        <span>{max}</span>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  note,
  accent = false,
}: {
  label: string;
  value: string;
  note: string;
  accent?: boolean;
}) {
  return (
    <div className={accent ? 'metric-card metric-card-accent' : 'metric-card'}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </p>
      <p className="mt-2 font-mono text-[clamp(1.65rem,3vw,2.4rem)] font-semibold leading-none tracking-[-0.05em] tabular-nums">
        {value}
      </p>
      <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{note}</p>
    </div>
  );
}

export function GpuEconomicsLab() {
  const [assumptions, setAssumptions] = useState(defaults);
  const assumptionsRef = useRef(assumptions);
  const result = useMemo(() => compute(assumptions), [assumptions]);

  useEffect(() => {
    assumptionsRef.current = assumptions;
  }, [assumptions]);

  useEffect(() => {
    const context = document.modelContext;
    if (!context?.registerTool) return;

    const lifecycle = new AbortController();
    const ranges: Record<keyof Assumptions, [number, number]> = {
      ownerUse: [0, 90],
      idleFill: [10, 100],
      hostRate: [0.3, 1.5],
      discount: [0, 40],
      periods: [12, 36],
      storageGb: [0, 300],
    };

    const register = context.registerTool(
      {
        name: 'set_gpu_economics_assumptions',
        title: 'Set GPU economics assumptions',
        description:
          'Update one or more visible Sqwish GPU Slack Lab assumptions and return the recalculated ex-VAT result.',
        inputSchema: {
          type: 'object',
          properties: {
            ownerUse: { type: 'number', minimum: 0, maximum: 90 },
            idleFill: { type: 'number', minimum: 10, maximum: 100 },
            hostRate: { type: 'number', minimum: 0.3, maximum: 1.5 },
            discount: { type: 'number', minimum: 0, maximum: 40 },
            periods: { type: 'number', minimum: 12, maximum: 36 },
            storageGb: { type: 'number', minimum: 0, maximum: 300 },
          },
          minProperties: 1,
          additionalProperties: false,
        },
        annotations: { readOnlyHint: false, untrustedContentHint: false },
        async execute(input) {
          if (!input || typeof input !== 'object' || Array.isArray(input)) {
            throw new Error('Assumptions must be a non-empty object.');
          }
          const entries = Object.entries(input as Record<string, unknown>);
          if (entries.length === 0) throw new Error('Provide at least one assumption.');

          const allowed = new Set(Object.keys(ranges));
          const next = { ...assumptionsRef.current };
          for (const [key, raw] of entries) {
            if (!allowed.has(key) || typeof raw !== 'number' || !Number.isFinite(raw)) {
              throw new Error(`Invalid assumption: ${key}`);
            }
            const typedKey = key as keyof Assumptions;
            const [minimum, maximum] = ranges[typedKey];
            if (raw < minimum || raw > maximum) {
              throw new Error(`${key} must be between ${minimum} and ${maximum}.`);
            }
            next[typedKey] = raw;
          }

          assumptionsRef.current = next;
          setAssumptions(next);
          await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
          const recalculated = compute(next);
          return {
            assumptions: next,
            effectiveCostGbp: Number(recalculated.effective.toFixed(2)),
            rentalIncomeGbp: Number(recalculated.income.toFixed(2)),
            termEffectiveCostGbp: Number(recalculated.termEffective.toFixed(2)),
          };
        },
      },
      { signal: lifecycle.signal },
    );

    void Promise.resolve(register).catch(() => undefined);
    return () => lifecycle.abort();
  }, []);

  const update = <K extends keyof Assumptions>(key: K, value: Assumptions[K]) => {
    setAssumptions((current) => ({ ...current, [key]: value }));
  };

  const scenarioRows = Object.entries(presets).map(([name, preset]) => {
    const values = compute({ ...assumptions, ...preset });
    return {
      name,
      value: Math.round(values.effective),
      fill: preset.idleFill,
      rate: preset.hostRate,
    };
  });

  return (
    <main className="min-h-screen overflow-hidden bg-background text-foreground">
      <div className="ambient-grid" aria-hidden="true" />
      <div className="relative mx-auto max-w-[1480px] px-4 py-5 sm:px-7 lg:px-10 lg:py-8">
        <header className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-border/70 pb-5">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl border border-primary/30 bg-primary/10 text-primary shadow-[0_0_35px_rgb(183_255_79/12%)]">
              <Zap className="size-5" />
            </div>
            <div>
              <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">
                Sqwish Labs / decision model
              </p>
              <h1 className="text-xl font-semibold tracking-[-0.035em] sm:text-2xl">
                GPU slack lab
              </h1>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="border-primary/30 bg-primary/5 text-primary">
              ex VAT
            </Badge>
            <Badge variant="outline" className="hidden sm:inline-flex">
              4 × RTX PRO 6000 WS
            </Badge>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setAssumptions(defaults)}
              aria-label="Reset all assumptions"
            >
              <RotateCcw /> Reset
            </Button>
          </div>
        </header>

        <section className="mb-6" aria-labelledby="capacity-loop-title">
          <Card className="capacity-loop overflow-hidden border-primary/25 bg-card/90 shadow-2xl shadow-black/10">
            <CardHeader className="border-b border-border/70">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle id="capacity-loop-title" className="text-lg sm:text-xl">
                    How spare compute becomes research capacity
                  </CardTitle>
                  <CardDescription className="mt-1 max-w-3xl leading-relaxed">
                    GPUs the team has released can earn on Vast.ai. A controlled two-A100 pilot now
                    shows a fast renter-to-research handoff, with one rating caveat:
                  </CardDescription>
                </div>
                <Badge variant="outline" className="border-primary/30 bg-primary/5 text-primary">
                  2 × A100 pilot complete
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <li className="loop-step">
                  <span className="loop-number">01</span>
                  <CircleDollarSign className="size-5 text-primary" aria-hidden="true" />
                  <div>
                    <h2 className="font-semibold tracking-tight">Offer spare GPUs</h2>
                    <p>List team-idle cards as interruptible compute on Vast.ai.</p>
                  </div>
                </li>
                <li className="loop-step">
                  <span className="loop-number">02</span>
                  <Undo2 className="size-5 text-primary" aria-hidden="true" />
                  <div>
                    <h2 className="font-semibold tracking-tight">Reclaim for research</h2>
                    <p>Unlist first, then start the exact pre-created owner standby. The pilot freed both cards in 82.3 seconds.</p>
                  </div>
                </li>
                <li className="loop-step">
                  <span className="loop-number">03</span>
                  <FlaskConical className="size-5 text-primary" aria-hidden="true" />
                  <div>
                    <h2 className="font-semibold tracking-tight">Run the team job</h2>
                    <p>A real PyTorch probe saw and used both A100s before the research window began.</p>
                  </div>
                </li>
                <li className="loop-step">
                  <span className="loop-number">04</span>
                  <Repeat2 className="size-5 text-primary" aria-hidden="true" />
                  <div>
                    <h2 className="font-semibold tracking-tight">Return spare capacity</h2>
                    <p>Stop the owner job; the interruptible renter resumes automatically, then the GPUs can be offered again.</p>
                  </div>
                </li>
              </ol>
              <div className="rounded-lg border border-primary/25 bg-primary/[0.045] p-4 text-sm leading-relaxed">
                <p className="font-semibold text-foreground">Pilot result: renter to owner in 82.3 seconds</p>
                <p className="mt-1 text-muted-foreground">
                  The controlled interruptible renter paused, the exact owner on-demand standby started,
                  and a real PyTorch check used both A100s. When the owner stopped, the renter returned
                  automatically. Final cleanup left the host unlisted with no pilot instances or public offers.
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  Market shape: public on-demand is deliberately expensive, reserved discount is zero,
                  and interruptible capacity is priced around comparable-market P10. Reclaim aborts if
                  any outside non-interruptible contract appears.
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  <strong className="text-foreground">Owner cost:</strong> the live own-machine instance
                  showed a $0 GPU charge. Its stopped disk still accrued a small storage charge. The
                  separate controlled-renter account pays ordinary marketplace charges during qualification;
                  that is a test expense, not the production owner path.
                </p>
                <p className="mt-2 text-xs text-muted-foreground">
                  Vast officially documents a free own-machine test instance and separately documents
                  on-demand priority over interruptibles. The retained-standby research loop combines those
                  supported components; the routine reclaim policy and a zero-rating-impact promise are not
                  documented guarantees.
                </p>
              </div>
              <div className="qualification-callout">
                <Asterisk aria-hidden="true" />
                <p>
                  <strong>Rating-safe production gate still open:</strong> reliability stayed at 0.5727243
                  immediately after handoff and after cleanup, so this cycle caused no observed drop. The
                  host was already below its immutable original 0.5999925 baseline. A later read-only sample
                  was 0.5727207 and measured only 161.9 Mbps upload, below Vast&apos;s current 500 Mbps
                  verification minimum. The disposable-host deadline still prevented the required two-hour
                  checkpoint. This proves the functional path once; it does not prove rating-safe routine
                  operation.
                </p>
              </div>
              <div className="qualification-callout border-sky-400/30 bg-sky-400/[0.055]">
                <ServerCog aria-hidden="true" />
                <p>
                  <strong>Verification-growth mode:</strong> while a new host is earning verification,
                  the operating lock keeps it steadily online and blocks the owner-standby takeover.
                  Team work must use Vast&apos;s supported Jobs/Create Job route during this phase. The
                  fast 82.3-second reclaim remains a separate research-first experiment until Vast
                  confirms that routine owner standby use will not prevent verification or lower rating.
                  The dedicated-box gate is a 24-hour controlled run: a qualification-trend soak first,
                  then an explicit mode transition and three four-GPU handoff/checkpoint/return cycles. A
                  separate no-owner soak is the strict verification control.
                </p>
              </div>
            </CardContent>
          </Card>
        </section>

        <section className="mb-6 grid gap-4 lg:grid-cols-[minmax(280px,0.72fr)_minmax(0,1.8fr)]">
          <Card className="control-panel border-border/80 bg-card/90 shadow-2xl shadow-black/10">
            <CardHeader className="border-b border-border/70 pb-4">
              <CardTitle className="flex items-center gap-2">
                <Gauge className="size-4 text-primary" /> Assumptions
              </CardTitle>
              <CardDescription>Drag the inputs. Every result updates immediately.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5 pt-1">
              <div className="grid grid-cols-3 gap-2">
                {Object.entries(presets).map(([name, preset]) => {
                  const active =
                    assumptions.idleFill === preset.idleFill &&
                    assumptions.hostRate === preset.hostRate &&
                    assumptions.discount === preset.discount;
                  return (
                    <Button
                      key={name}
                      size="sm"
                      variant={active ? 'default' : 'outline'}
                      onClick={() => setAssumptions((current) => ({ ...current, ...preset }))}
                      className="text-xs"
                    >
                      {name}
                    </Button>
                  );
                })}
              </div>
              <Control
                label="Sqwish owner allocation"
                value={assumptions.ownerUse}
                display={`${assumptions.ownerUse.toFixed(0)}%`}
                min={0}
                max={90}
                step={1}
                onChange={(value) => update('ownerUse', value)}
              />
              <Control
                label="Rental fill of idle hours"
                value={assumptions.idleFill}
                display={`${assumptions.idleFill.toFixed(1)}%`}
                min={10}
                max={100}
                step={0.1}
                onChange={(value) => update('idleFill', value)}
              />
              <Control
                label="Host earnings / GPU-hour"
                value={assumptions.hostRate}
                display={`$${assumptions.hostRate.toFixed(2)}`}
                min={0.3}
                max={1.5}
                step={0.01}
                onChange={(value) => update('hostRate', value)}
              />
              <Control
                label="SCAN commitment discount"
                value={assumptions.discount}
                display={`${assumptions.discount.toFixed(0)}%`}
                min={0}
                max={40}
                step={1}
                onChange={(value) => update('discount', value)}
              />
              <Control
                label="Stopped template storage"
                value={assumptions.storageGb}
                display={`${assumptions.storageGb.toFixed(0)} GB`}
                min={0}
                max={300}
                step={20}
                onChange={(value) => update('storageGb', value)}
              />
              <Control
                label="Commitment horizon"
                value={assumptions.periods}
                display={`${assumptions.periods.toFixed(0)} periods`}
                min={12}
                max={36}
                step={1}
                onChange={(value) => update('periods', value)}
              />
            </CardContent>
          </Card>

          <div className="grid min-w-0 gap-4">
            <Card className="hero-result border-primary/20 bg-card/85 shadow-2xl shadow-black/10">
              <CardContent className="grid gap-5 pt-1 xl:grid-cols-[1.12fr_0.88fr]">
                <div className="flex flex-col justify-between rounded-xl border border-primary/25 bg-primary/[0.055] p-5 sm:p-6">
                  <div>
                    <div className="mb-8 flex flex-wrap items-center justify-between gap-3">
                      <Badge className="bg-primary text-primary-foreground">
                        <Sparkles /> Live planning result
                      </Badge>
                      <span className="font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                        30-day equivalent
                      </span>
                    </div>
                    <p className="text-sm font-medium text-muted-foreground">Effective Sqwish cost</p>
                    <p className="mt-2 font-mono text-[clamp(3rem,8vw,6.7rem)] font-semibold leading-[0.84] tracking-[-0.075em] tabular-nums text-primary">
                      {money.format(result.effective)}
                    </p>
                    <p className="mt-4 max-w-xl text-sm leading-relaxed text-muted-foreground">
                      Discounted SCAN cost, minus Vast compute income, plus the conservative displayed charge for stopped owner-template storage.
                    </p>
                  </div>
                  <div className="mt-8 grid grid-cols-2 gap-3 border-t border-primary/20 pt-5 sm:grid-cols-3">
                    <div>
                      <p className="stat-label">SCAN</p>
                      <p className="stat-value">{money.format(result.scanCost)}</p>
                    </div>
                    <div>
                      <p className="stat-label">Vast income</p>
                      <p className="stat-value text-primary">−{money.format(result.income)}</p>
                    </div>
                    <div className="col-span-2 sm:col-span-1">
                      <p className="stat-label">Stopped disk</p>
                      <p className="stat-value">+{money.format(result.storage)}</p>
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <Metric
                    label={`${assumptions.periods}-period cost`}
                    value={money.format(result.termEffective)}
                    note={`${money.format(result.termScanCost)} SCAN less ${money.format(result.termIncome)} compute income.`}
                    accent
                  />
                  <Metric
                    label="Owner GPU-hours"
                    value={Math.round(result.ownerGpuHours).toLocaleString('en-GB')}
                    note={`Out of ${GPU_HOURS.toLocaleString('en-GB')} GPU-hours per 30 days.`}
                  />
                  <Metric
                    label="Break-even fill"
                    value={Number.isFinite(result.breakEvenFill) ? `${result.breakEvenFill.toFixed(1)}%` : '—'}
                    note="Required fill of owner-idle GPU-hours at this host rate."
                  />
                  <Metric
                    label="Cost / owner GPU-h"
                    value={result.effectivePerOwnerHour === null ? '—' : money.format(result.effectivePerOwnerHour)}
                    note="Useful only when the owner allocation is non-zero."
                  />
                </div>
              </CardContent>
            </Card>

            <Card className="border-border/80 bg-card/85">
              <CardHeader className="border-b border-border/70 pb-4">
                <CardTitle className="flex items-center gap-2">
                  <BadgePoundSterling className="size-4 text-primary" /> Scenario envelope
                </CardTitle>
                <CardDescription>
                  Same owner allocation and storage; market and commitment assumptions change.
                </CardDescription>
              </CardHeader>
              <CardContent className="pt-1">
                <ChartContainer config={chartConfig} className="h-[210px] w-full aspect-auto">
                  <BarChart data={scenarioRows} margin={{ top: 16, right: 12, left: 0, bottom: 0 }}>
                    <CartesianGrid vertical={false} strokeDasharray="3 5" />
                    <XAxis dataKey="name" tickLine={false} axisLine={false} tickMargin={10} />
                    <YAxis
                      tickLine={false}
                      axisLine={false}
                      width={54}
                      tickFormatter={(value) => `£${Math.round(value / 100) * 100}`}
                    />
                    <ChartTooltip
                      cursor={{ fill: 'var(--muted)', opacity: 0.35 }}
                      content={
                        <ChartTooltipContent
                          hideLabel
                          formatter={(value, _name, item) => (
                            <div className="grid min-w-36 grid-cols-[1fr_auto] gap-x-4 gap-y-1">
                              <span className="text-muted-foreground">Effective cost</span>
                              <span className="font-mono font-semibold">{money.format(Number(value))}</span>
                              <span className="text-muted-foreground">Idle fill</span>
                              <span className="font-mono">{item.payload.fill}%</span>
                              <span className="text-muted-foreground">Host rate</span>
                              <span className="font-mono">${item.payload.rate.toFixed(2)}</span>
                            </div>
                          )}
                        />
                      }
                    />
                    <Bar dataKey="value" radius={[7, 7, 2, 2]}>
                      {scenarioRows.map((row) => (
                        <Cell
                          key={row.name}
                          fill={row.name === 'Base' ? 'var(--primary)' : 'var(--chart-2)'}
                          opacity={row.name === 'Base' ? 1 : 0.55}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                </ChartContainer>
              </CardContent>
            </Card>
          </div>
        </section>

        <section className="grid gap-4 lg:grid-cols-3">
          <Card className="border-border/80 bg-card/80 lg:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <CircleHelp className="size-4 text-primary" /> Why the default is 20%
              </CardTitle>
              <CardDescription>Measured evidence for workload shape; an explicit prior for Sqwish volume.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 md:grid-cols-3">
              <div className="evidence-card">
                <p className="evidence-kicker">External evidence</p>
                <p className="evidence-number">Mostly 1-GPU</p>
                <p className="evidence-copy">Large production traces show many small jobs plus a tiny number of training campaigns that dominate GPU-hours.</p>
              </div>
              <div className="evidence-card border-primary/25 bg-primary/[0.045]">
                <p className="evidence-kicker text-primary">Sqwish prior</p>
                <p className="evidence-number">20% rounded</p>
                <p className="evidence-copy">The reproducible “normal” calendar is 558 / 2,880 GPU-hours, or 19.4%. It explains the prior; it is not observed Sqwish telemetry.</p>
              </div>
              <div className="evidence-card">
                <p className="evidence-kicker">Calibration rule</p>
                <p className="evidence-number">Measure month 1</p>
                <p className="evidence-copy">Replace this slider with allocated GPU-hours from the owner scheduler, including idle notebooks and reserved jobs.</p>
              </div>
            </CardContent>
          </Card>

          <Card className="border-border/80 bg-card/80">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ServerCog className="size-4 text-primary" /> Proof status
              </CardTitle>
              <CardDescription>What the controlled two-GPU qualification run actually demonstrated.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="proof-row proof-pass"><ArrowUpRight /> A controlled interruptible renter held both A100s with a 10 GB disk cap</div>
              <div className="proof-row proof-pass"><ArrowUpRight /> Owner reclaim completed in 82.3 seconds; PyTorch saw and used both GPUs</div>
              <div className="proof-row proof-pass"><ArrowUpRight /> Stopping the owner automatically returned the controlled renter</div>
              <div className="proof-row proof-pass"><ArrowUpRight /> Reliability stayed at 0.5727243 immediately and after cleanup</div>
              <div className="proof-row proof-pass"><ArrowUpRight /> Final cleanup left no pilot instances or public offers</div>
              <div className="proof-row proof-open"><ArrowDownRight /> 0.5727243 remains below the immutable original 0.5999925 baseline</div>
              <div className="proof-row proof-open"><ArrowDownRight /> No delayed rating check was possible before the disposable VM deadline</div>
              <p className="rounded-md border border-border/70 bg-muted/35 p-3 text-xs leading-relaxed text-muted-foreground">
                The functional handoff passed on this disposable two-A100 pilot. One degraded diagnostic
                cycle cannot establish rating-safe production use; repeat it on the dedicated host with
                delayed reliability checks before making that promise.
              </p>
            </CardContent>
          </Card>
        </section>

        <footer className="mt-6 flex flex-col gap-3 border-t border-border/70 py-5 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-center gap-2">
            <Asterisk className="size-3 text-primary" /> Planning model, checked 2 September 2026. Market data moves.
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            <a className="source-link" href="https://www.scan.co.uk/products/3xs-sc-pb4-32t-1-month-4x-96gb-nvidia-rtx-pro-6000-512gb-ddr5-ecc-amd-epyc-9354p" target="_blank" rel="noreferrer">SCAN price <ExternalLink /></a>
            <a className="source-link" href="https://cloud.vast.ai/host/market/" target="_blank" rel="noreferrer">Vast market <ExternalLink /></a>
            <a className="source-link" href="https://docs.vast.ai/host/verification-stages" target="_blank" rel="noreferrer">Verification stages <ExternalLink /></a>
            <a className="source-link" href="https://docs.vast.ai/host/hosting-overview" target="_blank" rel="noreferrer">Own-machine testing <ExternalLink /></a>
            <a className="source-link" href="https://docs.vast.ai/guides/instances/choosing/instance-types" target="_blank" rel="noreferrer">Instance priorities <ExternalLink /></a>
            <a className="source-link" href="https://docs.vast.ai/cli/reference/start-instance" target="_blank" rel="noreferrer">Start standby <ExternalLink /></a>
            <a className="source-link" href="https://www.usenix.org/system/files/atc19-jeon.pdf" target="_blank" rel="noreferrer">Workload evidence <ExternalLink /></a>
          </div>
        </footer>
      </div>
    </main>
  );
}
