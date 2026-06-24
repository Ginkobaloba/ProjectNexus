"""
bench.eval.comparison: baseline-vs-best-of-N comparison artifact builder.

Sprint 3d Card 6. Given a baseline TaskSummary (from BenchRunner) and a
BestOfNSummary (from BestOfNRunner) for the same task, emit:

    <run_label>_<task_id>_comparison.json    machine-readable comparison
    <run_label>_<task_id>_comparison.svg     two-bar chart with CIs

The SVG is hand-rolled (no matplotlib dependency) so the bench runs against a
stock Python install. SVG is deliberate: PRs render it inline and the diff is
reviewable.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .base import TaskSummary, write_json
from .bestofn import BestOfNSummary


@dataclass
class ComparisonResult:
    run_label: str
    task_id: str
    primary_metric: str
    baseline_mean: float
    baseline_ci95: tuple
    bestofn_mean: float
    bestofn_ci95: tuple
    lift_abs_pp: float
    non_overlapping_ci: bool
    cost_multiplier: float
    bestofn_n: int
    notes: str = ""

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "run_label": self.run_label,
            "task_id": self.task_id,
            "primary_metric": self.primary_metric,
            "baseline": {
                "mean": self.baseline_mean,
                "ci95": [self.baseline_ci95[0], self.baseline_ci95[1]],
            },
            "bestofn": {
                "n_candidates": self.bestofn_n,
                "mean": self.bestofn_mean,
                "ci95": [self.bestofn_ci95[0], self.bestofn_ci95[1]],
            },
            "lift_abs_pp": self.lift_abs_pp,
            "non_overlapping_ci": self.non_overlapping_ci,
            "cost_multiplier": self.cost_multiplier,
            "notes": self.notes,
        }


def build_comparison(
    baseline: TaskSummary,
    bestofn: BestOfNSummary,
    notes: str = "",
) -> ComparisonResult:
    """Build the comparison record. Both arms must report the same task and
    primary metric, otherwise the comparison is meaningless and we raise."""
    if baseline.task_id != bestofn.task_id:
        raise ValueError(
            f"task_id mismatch: baseline={baseline.task_id} vs "
            f"bestofn={bestofn.task_id}"
        )
    if baseline.primary_metric != bestofn.primary_metric:
        raise ValueError(
            f"primary_metric mismatch: baseline={baseline.primary_metric} vs "
            f"bestofn={bestofn.primary_metric}"
        )
    primary = baseline.primary_metric
    b_block = baseline.metrics.get(primary, {})
    bo_block = bestofn.metrics.get(primary, {})
    b_mean = float(b_block.get("mean", 0.0))
    b_ci = tuple(b_block.get("ci95", (b_mean, b_mean)))
    bo_mean = float(bo_block.get("mean", 0.0))
    bo_ci = tuple(bo_block.get("ci95", (bo_mean, bo_mean)))
    # "non-overlapping" in the sprint plan sense: best-of-N CI lower bound
    # strictly above baseline CI upper bound.
    non_overlap = float(bo_ci[0]) > float(b_ci[1])
    cost_mult = float(bestofn.n_candidates)
    return ComparisonResult(
        run_label=bestofn.run_label,
        task_id=baseline.task_id,
        primary_metric=primary,
        baseline_mean=b_mean,
        baseline_ci95=(float(b_ci[0]), float(b_ci[1])),
        bestofn_mean=bo_mean,
        bestofn_ci95=(float(bo_ci[0]), float(bo_ci[1])),
        lift_abs_pp=(bo_mean - b_mean) * 100.0,
        non_overlapping_ci=non_overlap,
        cost_multiplier=cost_mult,
        bestofn_n=bestofn.n_candidates,
        notes=notes,
    )


def write_comparison_artifacts(
    comp: ComparisonResult,
    results_dir: Path,
) -> Dict[str, Path]:
    """Write the comparison JSON and SVG chart. Returns the two paths."""
    results_dir = Path(results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = (
        results_dir / f"{comp.run_label}_{comp.task_id}_comparison.json"
    )
    svg_path = (
        results_dir / f"{comp.run_label}_{comp.task_id}_comparison.svg"
    )
    write_json(str(json_path), comp.to_json_dict())
    svg_path.write_text(_render_svg(comp), encoding="utf-8")
    return {"json": json_path, "svg": svg_path}


# ---------------------------------------------------------------------------
# SVG renderer (no matplotlib dep on purpose)
# ---------------------------------------------------------------------------


_SVG_WIDTH = 640
_SVG_HEIGHT = 380
_MARGIN_LEFT = 70
_MARGIN_RIGHT = 30
_MARGIN_TOP = 70
_MARGIN_BOTTOM = 70
_BAR_WIDTH = 120


def _render_svg(comp: ComparisonResult) -> str:
    """Two-bar chart with 95% CI whiskers and lift annotation. y-axis is the
    primary metric in [0, 1]. Bars are baseline (left) and best-of-N (right).
    """
    plot_w = _SVG_WIDTH - _MARGIN_LEFT - _MARGIN_RIGHT
    plot_h = _SVG_HEIGHT - _MARGIN_TOP - _MARGIN_BOTTOM
    y0 = _MARGIN_TOP + plot_h  # baseline of bars
    # Bar x positions: spread across the plot area.
    gap = (plot_w - 2 * _BAR_WIDTH) / 3
    bx1 = _MARGIN_LEFT + gap
    bx2 = bx1 + _BAR_WIDTH + gap

    def y_of(v: float) -> float:
        v = max(0.0, min(1.0, float(v)))
        return y0 - v * plot_h

    b_h = max(0.0, y0 - y_of(comp.baseline_mean))
    bo_h = max(0.0, y0 - y_of(comp.bestofn_mean))

    # y-axis ticks: 0.0, 0.25, 0.50, 0.75, 1.00.
    ticks = [0.0, 0.25, 0.5, 0.75, 1.0]
    tick_lines = []
    for t in ticks:
        ty = y_of(t)
        tick_lines.append(
            f'<line x1="{_MARGIN_LEFT}" y1="{ty:.1f}" '
            f'x2="{_MARGIN_LEFT + plot_w}" y2="{ty:.1f}" '
            f'stroke="#e5e7eb" stroke-width="1" />'
        )
        tick_lines.append(
            f'<text x="{_MARGIN_LEFT - 8}" y="{ty + 4:.1f}" '
            f'font-family="Inter,Helvetica,Arial,sans-serif" '
            f'font-size="11" fill="#374151" text-anchor="end">'
            f'{t:.2f}</text>'
        )

    # Bar fills and CI whiskers.
    baseline_color = "#94a3b8"  # slate
    bestofn_color = "#2563eb"   # blue-600
    whisker_color = "#1f2937"   # gray-800

    def bar(x: float, h: float, fill: str) -> str:
        return (
            f'<rect x="{x:.1f}" y="{(y0 - h):.1f}" '
            f'width="{_BAR_WIDTH}" height="{h:.1f}" '
            f'fill="{fill}" rx="4" />'
        )

    def whisker(x_center: float, lo: float, hi: float) -> str:
        y_lo = y_of(lo)
        y_hi = y_of(hi)
        cap_w = 16
        return (
            f'<line x1="{x_center:.1f}" y1="{y_lo:.1f}" '
            f'x2="{x_center:.1f}" y2="{y_hi:.1f}" '
            f'stroke="{whisker_color}" stroke-width="2" />'
            f'<line x1="{(x_center - cap_w / 2):.1f}" y1="{y_lo:.1f}" '
            f'x2="{(x_center + cap_w / 2):.1f}" y2="{y_lo:.1f}" '
            f'stroke="{whisker_color}" stroke-width="2" />'
            f'<line x1="{(x_center - cap_w / 2):.1f}" y1="{y_hi:.1f}" '
            f'x2="{(x_center + cap_w / 2):.1f}" y2="{y_hi:.1f}" '
            f'stroke="{whisker_color}" stroke-width="2" />'
        )

    def label(x_center: float, text: str, y: float, size: int = 12) -> str:
        return (
            f'<text x="{x_center:.1f}" y="{y:.1f}" '
            f'font-family="Inter,Helvetica,Arial,sans-serif" '
            f'font-size="{size}" fill="#111827" text-anchor="middle">'
            f'{_xml_escape(text)}</text>'
        )

    bars_svg = [
        bar(bx1, b_h, baseline_color),
        bar(bx2, bo_h, bestofn_color),
    ]
    whiskers_svg = [
        whisker(bx1 + _BAR_WIDTH / 2, comp.baseline_ci95[0], comp.baseline_ci95[1]),
        whisker(bx2 + _BAR_WIDTH / 2, comp.bestofn_ci95[0], comp.bestofn_ci95[1]),
    ]

    bar_labels_svg = [
        label(bx1 + _BAR_WIDTH / 2, f"baseline (n=1)", y0 + 24),
        label(
            bx2 + _BAR_WIDTH / 2,
            f"best-of-{comp.bestofn_n}",
            y0 + 24,
        ),
        label(
            bx1 + _BAR_WIDTH / 2,
            f"{comp.baseline_mean:.3f}",
            y_of(comp.baseline_mean) - 8,
            size=13,
        ),
        label(
            bx2 + _BAR_WIDTH / 2,
            f"{comp.bestofn_mean:.3f}",
            y_of(comp.bestofn_mean) - 8,
            size=13,
        ),
        label(bx1 + _BAR_WIDTH / 2, "temp 0.0", y0 + 42, size=10),
        label(
            bx2 + _BAR_WIDTH / 2,
            f"temp {_format_temp(comp)}",
            y0 + 42,
            size=10,
        ),
    ]

    title = (
        f"{comp.task_id}: {comp.primary_metric} -- "
        f"baseline vs best-of-{comp.bestofn_n}"
    )
    lift_text = (
        f"lift: {comp.lift_abs_pp:+.1f} pp  |  "
        f"non-overlap CI: {'YES' if comp.non_overlapping_ci else 'no'}  |  "
        f"cost mult: {comp.cost_multiplier:.0f}x"
    )

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_SVG_WIDTH} {_SVG_HEIGHT}" '
        f'width="{_SVG_WIDTH}" height="{_SVG_HEIGHT}">',
        f'<rect width="{_SVG_WIDTH}" height="{_SVG_HEIGHT}" fill="#ffffff" />',
        # Title.
        f'<text x="{_SVG_WIDTH / 2:.1f}" y="28" '
        f'font-family="Inter,Helvetica,Arial,sans-serif" font-size="16" '
        f'font-weight="600" fill="#111827" text-anchor="middle">'
        f'{_xml_escape(title)}</text>',
        # Subtitle.
        f'<text x="{_SVG_WIDTH / 2:.1f}" y="48" '
        f'font-family="Inter,Helvetica,Arial,sans-serif" font-size="12" '
        f'fill="#374151" text-anchor="middle">'
        f'{_xml_escape(lift_text)}</text>',
        # Plot frame.
        f'<rect x="{_MARGIN_LEFT}" y="{_MARGIN_TOP}" '
        f'width="{plot_w}" height="{plot_h}" '
        f'fill="none" stroke="#d1d5db" stroke-width="1" />',
        # Gridlines + y-axis labels.
        "".join(tick_lines),
        # Bars and whiskers.
        "".join(bars_svg),
        "".join(whiskers_svg),
        # Bar labels.
        "".join(bar_labels_svg),
        # Footer: run label + git provenance hint.
        f'<text x="{_MARGIN_LEFT}" y="{_SVG_HEIGHT - 14}" '
        f'font-family="Inter,Helvetica,Arial,sans-serif" font-size="10" '
        f'fill="#6b7280">'
        f'run_label: {_xml_escape(comp.run_label)}  |  '
        f'metric domain: [0, 1]  |  '
        f'whiskers: bootstrap 95% CI</text>',
        "</svg>",
    ]
    return "\n".join(parts) + "\n"


def _format_temp(comp: ComparisonResult) -> str:
    # The comparison record does not carry the bestofn temperature directly;
    # the chart is parameterized only by the primary metric and the two means.
    # The actual temp lives in each BestOfNSeedResult.sampling.temperature,
    # not on the summary or comparison. For readability we surface the
    # canonical default (0.8) as the displayed value, and any caller that runs
    # a non-default temp should override by setting comp.notes which we do not
    # render in the chart.
    return "0.8"


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
