#!/usr/bin/env python3
"""Small, dependency-free calculator for the SCAN/Vast hosting model."""

from __future__ import annotations

import argparse


def percent(value: str) -> float:
    number = float(value)
    if not 0 <= number <= 100:
        raise argparse.ArgumentTypeError("percentage must be between 0 and 100")
    return number / 100.0


def positive(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate SCAN lease cost after Vast interruptible host earnings. "
            "The host rate is the amount the host earns, not the higher client-facing bid."
        )
    )
    parser.add_argument(
        "--scan-monthly-ex-vat-gbp",
        type=positive,
        default=1666.65,
        help="recoverable-VAT decision cost; default is SCAN's public ex-VAT price",
    )
    parser.add_argument("--discount-percent", type=percent, default=0.25)
    parser.add_argument("--gpus", type=int, default=4)
    parser.add_argument("--days", type=positive, default=30.0)
    parser.add_argument(
        "--commitment-periods",
        type=int,
        default=18,
        help="number of identical billing periods to total; default 18",
    )
    parser.add_argument(
        "--owner-use-percent",
        type=percent,
        default=0.20,
        help="rounded planning prior; calibrate from scheduler allocation telemetry",
    )
    parser.add_argument(
        "--idle-fill-percent",
        type=percent,
        default=13.4 / 18.0,
        help="default 18-period ramp mean: 2x50%, 4x70%, then 12x80%",
    )
    parser.add_argument(
        "--host-rate-usd",
        type=positive,
        default=0.80,
        help="host-earned USD per GPU-hour; default is the 2026-09-02 WS quick-fill case",
    )
    parser.add_argument(
        "--usd-per-gbp",
        type=positive,
        default=1.1590 / 0.85655,
        help="USD received for one GBP; default is the ECB 2026-09-01 cross-rate",
    )
    parser.add_argument(
        "--other-host-income-gbp",
        type=float,
        default=0.0,
        help="Measured monthly storage/bandwidth income; leave zero until evidenced",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.gpus <= 0:
        raise SystemExit("--gpus must be positive")
    if args.commitment_periods <= 0:
        raise SystemExit("--commitment-periods must be positive")

    hours = args.days * 24.0
    total_gpu_hours = args.gpus * hours
    owner_gpu_hours = total_gpu_hours * args.owner_use_percent
    sellable_gpu_hours = total_gpu_hours - owner_gpu_hours
    rented_gpu_hours = sellable_gpu_hours * args.idle_fill_percent

    compute_usd = rented_gpu_hours * args.host_rate_usd
    compute_gbp = compute_usd / args.usd_per_gbp
    host_income_gbp = compute_gbp + args.other_host_income_gbp

    discounted_ex_vat = args.scan_monthly_ex_vat_gbp * (1.0 - args.discount_percent)
    effective_ex_vat = discounted_ex_vat - host_income_gbp

    max_compute_gbp = sellable_gpu_hours * args.host_rate_usd / args.usd_per_gbp
    break_even_fill_ex = discounted_ex_vat / max_compute_gbp if max_compute_gbp else float("inf")

    print(f"Period:                    {args.days:g} days ({hours:,.0f} hours)")
    print(f"GPU-hours available:       {total_gpu_hours:,.1f}")
    print(f"Sqwish GPU-hours:          {owner_gpu_hours:,.1f}")
    print(f"Rented GPU-hours:          {rented_gpu_hours:,.1f}")
    print(f"Vast compute income:       USD {compute_usd:,.2f} / GBP {compute_gbp:,.2f}")
    print(f"Other evidenced income:    GBP {args.other_host_income_gbp:,.2f}")
    print(f"Discounted SCAN ex VAT:    GBP {discounted_ex_vat:,.2f}")
    print(f"Effective cost ex VAT:     GBP {effective_ex_vat:,.2f}")

    if owner_gpu_hours:
        print(
            "Effective GBP/Sqwish GPU-h: "
            f"GBP {effective_ex_vat / owner_gpu_hours:,.3f} ex VAT"
        )
    else:
        print("Effective GBP/Sqwish GPU-h: n/a (owner use is zero)")

    print(f"Break-even idle fill:      {break_even_fill_ex * 100:,.1f}% ex VAT")
    print(
        f"{args.commitment_periods}-period SCAN charge:  "
        f"GBP {discounted_ex_vat * args.commitment_periods:,.2f} ex VAT"
    )
    print(
        f"{args.commitment_periods}-period host income:  "
        f"GBP {host_income_gbp * args.commitment_periods:,.2f}"
    )
    print(
        f"{args.commitment_periods}-period effective:   "
        f"GBP {effective_ex_vat * args.commitment_periods:,.2f} ex VAT"
    )


if __name__ == "__main__":
    main()
