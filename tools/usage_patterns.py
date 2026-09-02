#!/usr/bin/env python3
"""Transparent workload-shaped economics for a four-GPU research node."""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Block:
    label: str
    starts: int
    hours_each: int
    gpus: int

    @property
    def wall_hours(self) -> int:
        return self.starts * self.hours_each

    @property
    def gpu_hours(self) -> int:
        return self.wall_hours * self.gpus


@dataclass(frozen=True)
class Pattern:
    name: str
    blocks: tuple[Block, ...]
    # Wall-clock hours at exactly 0, 1, 2, 3, and 4 owner GPUs.
    concurrency_hours: tuple[int, int, int, int, int]


PATTERNS = (
    Pattern(
        "Light prototyping",
        (
            Block("per-researcher single-GPU sessions", 36, 4, 1),
            Block("shared two-GPU experiments", 4, 6, 2),
            Block("short four-GPU validation runs", 2, 4, 4),
        ),
        (552, 128, 32, 0, 8),
    ),
    Pattern(
        "Normal mixed R&D",
        (
            Block("per-researcher single-GPU sessions", 45, 6, 1),
            Block("shared two-GPU experiments", 8, 12, 2),
            Block("four-GPU training runs", 2, 12, 4),
        ),
        (370, 190, 136, 0, 24),
    ),
    Pattern(
        "Active training campaign",
        (
            Block("per-researcher single-GPU sessions", 30, 6, 1),
            Block("shared two-GPU experiments", 10, 24, 2),
            Block("four-GPU training runs", 5, 32, 4),
        ),
        (170, 120, 270, 0, 160),
    ),
    Pattern(
        "Deadline month",
        (
            Block("single-GPU sessions", 10, 6, 1),
            Block("two-GPU training runs", 10, 16, 2),
            Block("roughly week-long four-GPU campaigns", 3, 160, 4),
        ),
        (40, 20, 180, 0, 480),
    ),
)


def positive(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def percent(value: str) -> float:
    parsed = float(value)
    if not 0 <= parsed <= 100:
        raise argparse.ArgumentTypeError("percentage must be between 0 and 100")
    return parsed / 100.0


def nearest_rank(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare transparent 30-day research usage patterns on four GPUs."
    )
    parser.add_argument("--host-rate-usd", type=positive, default=0.80)
    parser.add_argument("--idle-fill-percent", type=percent, default=0.80)
    parser.add_argument("--usd-per-gbp", type=positive, default=1.1590 / 0.85655)
    parser.add_argument(
        "--scan-ex-vat-cost-gbp",
        type=positive,
        default=1666.65 * 0.75,
        help="discounted ex-VAT cost for one 30-day period",
    )
    args = parser.parse_args()

    total_hours = 30 * 24
    total_gpu_hours = 4 * total_hours
    print(
        "Pattern | Mean owner use | P50/P95/peak GPUs | Owner starts | "
        "Starts needing reclaim | Expected tenant pauses | Vast income | "
        "Effective SCAN cost ex VAT"
    )
    print("--- | ---: | ---: | ---: | ---: | ---: | ---: | ---:")

    for pattern in PATTERNS:
        if sum(pattern.concurrency_hours) != total_hours:
            raise RuntimeError(f"{pattern.name} concurrency calendar is not 720 hours")
        concurrency = [
            gpus
            for gpus, hours_at_concurrency in enumerate(pattern.concurrency_hours)
            for _ in range(hours_at_concurrency)
        ]

        owner_gpu_hours = sum(concurrency)
        block_gpu_hours = sum(block.gpu_hours for block in pattern.blocks)
        if owner_gpu_hours != block_gpu_hours:
            raise RuntimeError(f"{pattern.name} block and calendar GPU-hours disagree")
        idle_gpu_hours = total_gpu_hours - owner_gpu_hours
        sold_gpu_hours = idle_gpu_hours * args.idle_fill_percent
        revenue_gbp = sold_gpu_hours * args.host_rate_usd / args.usd_per_gbp
        effective_ex = args.scan_ex_vat_cost_gbp - revenue_gbp
        starts = sum(block.starts for block in pattern.blocks)
        starts_needing_reclaim = sum(
            block.starts * (1.0 - (1.0 - args.idle_fill_percent) ** block.gpus)
            for block in pattern.blocks
        )
        expected_tenant_pauses = sum(
            block.starts * block.gpus * args.idle_fill_percent
            for block in pattern.blocks
        )

        print(
            f"{pattern.name} | {owner_gpu_hours / total_gpu_hours:.1%} "
            f"({owner_gpu_hours:,} GPU-h) | "
            f"{nearest_rank(concurrency, 0.50)}/"
            f"{nearest_rank(concurrency, 0.95)}/{max(concurrency)} | "
            f"{starts} | {starts_needing_reclaim:,.0f} | "
            f"{expected_tenant_pauses:,.0f} | GBP {revenue_gbp:,.0f} | "
            f"GBP {effective_ex:,.0f}"
        )

    print()
    print("Workload assumptions (researcher blocks may overlap):")
    for pattern in PATTERNS:
        parts = [
            f"{block.starts} x {block.hours_each}h x {block.gpus} GPU "
            f"{block.label}"
            for block in pattern.blocks
        ]
        print(f"- {pattern.name}: " + "; ".join(parts) + ".")

    print()
    print(
        "Reclaim estimates treat each requested GPU as independently rented at the "
        "configured fill when a reservation starts. Adjacent owner windows, correlated "
        "rental occupancy, and already-paused tenants change the real count."
    )


if __name__ == "__main__":
    main()
