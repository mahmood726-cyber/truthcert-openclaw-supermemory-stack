"""
Forest Plot Generator for Meta-Analysis Claims

Generates SVG forest plots for certified meta-analysis results.
Only renders data from PASS bundles with valid signatures.
"""

import html
import math
from dataclasses import dataclass, field
from typing import Any, Optional, List
from pathlib import Path


@dataclass
class StudyData:
    """Data for a single study in the forest plot."""
    study_id: str
    study_label: str
    effect_size: float
    lower_ci: float
    upper_ci: float
    weight: float = 0.0
    n_total: Optional[int] = None
    n_events: Optional[int] = None
    subgroup: Optional[str] = None


@dataclass
class PooledEstimate:
    """Pooled effect estimate (diamond)."""
    effect_size: float
    lower_ci: float
    upper_ci: float
    model: str = "random"  # "fixed" or "random"
    i_squared: Optional[float] = None
    tau_squared: Optional[float] = None
    p_heterogeneity: Optional[float] = None


@dataclass
class ForestPlotConfig:
    """Configuration for forest plot appearance."""
    width: int = 800
    height_per_study: int = 25
    min_height: int = 200
    margin_left: int = 200
    margin_right: int = 150
    margin_top: int = 50
    margin_bottom: int = 80

    # Styling
    font_family: str = "Arial, sans-serif"
    font_size: int = 11
    title_font_size: int = 14

    # Colors
    study_color: str = "#2563eb"
    pooled_color: str = "#dc2626"
    null_line_color: str = "#6b7280"
    grid_color: str = "#e5e7eb"
    text_color: str = "#111827"

    # Effect size scale
    null_value: float = 1.0  # 1.0 for ratios, 0.0 for differences
    log_scale: bool = True   # Use log scale for ratio measures
    x_min: Optional[float] = None
    x_max: Optional[float] = None

    # Labels
    effect_label: str = "Effect Size"
    favors_left: str = "Favors Treatment"
    favors_right: str = "Favors Control"


class ForestPlotGenerator:
    """
    Generates SVG forest plots for meta-analysis results.

    CRITICAL: Only generates plots from certified data.
    """

    def __init__(self, config: Optional[ForestPlotConfig] = None):
        self.config = config or ForestPlotConfig()

    def generate(
        self,
        studies: List[StudyData],
        pooled: Optional[PooledEstimate] = None,
        title: str = "Forest Plot",
    ) -> str:
        """
        Generate SVG forest plot.

        Args:
            studies: List of study data
            pooled: Optional pooled estimate
            title: Plot title

        Returns:
            SVG string
        """
        if not studies:
            return self._empty_plot_svg(title)

        c = self.config

        # Calculate dimensions
        n_rows = len(studies) + (1 if pooled else 0) + 1  # +1 for header
        height = max(c.min_height, c.margin_top + n_rows * c.height_per_study + c.margin_bottom)

        # Calculate x-axis scale
        x_min, x_max = self._calculate_x_range(studies, pooled)
        plot_width = c.width - c.margin_left - c.margin_right

        # Start SVG
        svg_parts = [self._svg_header(c.width, height)]

        # Add styles
        svg_parts.append(self._svg_styles())

        # Add title
        svg_parts.append(f'''
            <text x="{c.width / 2}" y="25" class="title" text-anchor="middle">{html.escape(title)}</text>
        ''')

        # Add header row
        y_header = c.margin_top
        svg_parts.append(self._header_row(y_header))

        # Add grid lines
        svg_parts.append(self._grid_lines(x_min, x_max, plot_width, height))

        # Add null line
        null_x = self._value_to_x(c.null_value, x_min, x_max, plot_width)
        svg_parts.append(f'''
            <line x1="{c.margin_left + null_x}" y1="{c.margin_top + c.height_per_study}"
                  x2="{c.margin_left + null_x}" y2="{height - c.margin_bottom}"
                  class="null-line" stroke-dasharray="4,4"/>
        ''')

        # Add studies
        for i, study in enumerate(studies):
            y = c.margin_top + (i + 1) * c.height_per_study + c.height_per_study / 2
            svg_parts.append(self._study_row(study, y, x_min, x_max, plot_width))

        # Add pooled estimate (diamond)
        if pooled:
            y_pooled = c.margin_top + (len(studies) + 1) * c.height_per_study + c.height_per_study / 2
            svg_parts.append(self._pooled_row(pooled, y_pooled, x_min, x_max, plot_width))

        # Add x-axis
        svg_parts.append(self._x_axis(x_min, x_max, plot_width, height))

        # Add heterogeneity info if pooled
        if pooled and pooled.i_squared is not None:
            y_het = height - 15
            het_text = f"Heterogeneity: I² = {pooled.i_squared:.1f}%"
            if pooled.tau_squared is not None:
                het_text += f", τ² = {pooled.tau_squared:.4f}"
            if pooled.p_heterogeneity is not None:
                het_text += f", p = {pooled.p_heterogeneity:.3f}"
            svg_parts.append(f'''
                <text x="{c.margin_left}" y="{y_het}" class="het-text">{html.escape(het_text)}</text>
            ''')

        # Close SVG
        svg_parts.append("</svg>")

        return "\n".join(svg_parts)

    def _svg_header(self, width: int, height: int) -> str:
        """Generate SVG header."""
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"
            width="{width}" height="{height}" class="forest-plot">'''

    def _svg_styles(self) -> str:
        """Generate SVG styles."""
        c = self.config
        return f'''
        <defs>
            <style>
                .forest-plot {{
                    font-family: {c.font_family};
                    font-size: {c.font_size}px;
                }}
                .title {{
                    font-size: {c.title_font_size}px;
                    font-weight: bold;
                    fill: {c.text_color};
                }}
                .header {{
                    font-weight: bold;
                    fill: {c.text_color};
                }}
                .study-label {{
                    fill: {c.text_color};
                }}
                .study-point {{
                    fill: {c.study_color};
                }}
                .study-line {{
                    stroke: {c.study_color};
                    stroke-width: 1.5;
                }}
                .pooled-diamond {{
                    fill: {c.pooled_color};
                }}
                .null-line {{
                    stroke: {c.null_line_color};
                    stroke-width: 1;
                }}
                .grid-line {{
                    stroke: {c.grid_color};
                    stroke-width: 0.5;
                }}
                .axis-line {{
                    stroke: {c.text_color};
                    stroke-width: 1;
                }}
                .axis-label {{
                    fill: {c.text_color};
                    font-size: {c.font_size - 1}px;
                }}
                .het-text {{
                    fill: {c.text_color};
                    font-size: {c.font_size - 1}px;
                    font-style: italic;
                }}
                .effect-text {{
                    fill: {c.text_color};
                    font-size: {c.font_size - 1}px;
                }}
                .weight-text {{
                    fill: {c.text_color};
                    font-size: {c.font_size - 1}px;
                }}
            </style>
        </defs>
        '''

    def _header_row(self, y: float) -> str:
        """Generate header row."""
        c = self.config
        return f'''
            <text x="10" y="{y}" class="header">Study</text>
            <text x="{c.margin_left + (c.width - c.margin_left - c.margin_right) / 2}" y="{y}"
                  class="header" text-anchor="middle">{html.escape(c.effect_label)}</text>
            <text x="{c.width - c.margin_right + 10}" y="{y}" class="header">Effect [95% CI]</text>
            <text x="{c.width - 30}" y="{y}" class="header">Weight</text>
        '''

    def _study_row(
        self,
        study: StudyData,
        y: float,
        x_min: float,
        x_max: float,
        plot_width: float,
    ) -> str:
        """Generate a study row with point estimate and CI."""
        c = self.config

        # Study label
        label = html.escape(study.study_label[:25])  # Truncate long labels

        # Calculate positions
        effect_x = self._value_to_x(study.effect_size, x_min, x_max, plot_width)
        lower_x = self._value_to_x(study.lower_ci, x_min, x_max, plot_width)
        upper_x = self._value_to_x(study.upper_ci, x_min, x_max, plot_width)

        # Point size based on weight
        point_size = max(3, min(10, 3 + study.weight * 0.5))

        # Format effect text
        if c.log_scale:
            effect_text = f"{study.effect_size:.2f} [{study.lower_ci:.2f}, {study.upper_ci:.2f}]"
        else:
            effect_text = f"{study.effect_size:.2f} [{study.lower_ci:.2f}, {study.upper_ci:.2f}]"

        weight_text = f"{study.weight:.1f}%" if study.weight > 0 else ""

        return f'''
            <g class="study-row">
                <text x="10" y="{y + 4}" class="study-label">{label}</text>
                <line x1="{c.margin_left + max(0, lower_x)}" y1="{y}"
                      x2="{c.margin_left + min(plot_width, upper_x)}" y2="{y}"
                      class="study-line"/>
                <rect x="{c.margin_left + effect_x - point_size/2}" y="{y - point_size/2}"
                      width="{point_size}" height="{point_size}" class="study-point"/>
                <text x="{c.width - c.margin_right + 10}" y="{y + 4}" class="effect-text">{effect_text}</text>
                <text x="{c.width - 30}" y="{y + 4}" class="weight-text">{weight_text}</text>
            </g>
        '''

    def _pooled_row(
        self,
        pooled: PooledEstimate,
        y: float,
        x_min: float,
        x_max: float,
        plot_width: float,
    ) -> str:
        """Generate pooled estimate row (diamond)."""
        c = self.config

        # Calculate diamond points
        center_x = self._value_to_x(pooled.effect_size, x_min, x_max, plot_width)
        lower_x = self._value_to_x(pooled.lower_ci, x_min, x_max, plot_width)
        upper_x = self._value_to_x(pooled.upper_ci, x_min, x_max, plot_width)

        diamond_height = 8
        points = f"{c.margin_left + lower_x},{y} {c.margin_left + center_x},{y - diamond_height/2} " \
                 f"{c.margin_left + upper_x},{y} {c.margin_left + center_x},{y + diamond_height/2}"

        model_label = "Overall (Random)" if pooled.model == "random" else "Overall (Fixed)"
        effect_text = f"{pooled.effect_size:.2f} [{pooled.lower_ci:.2f}, {pooled.upper_ci:.2f}]"

        return f'''
            <g class="pooled-row">
                <text x="10" y="{y + 4}" class="study-label" font-weight="bold">{model_label}</text>
                <polygon points="{points}" class="pooled-diamond"/>
                <text x="{c.width - c.margin_right + 10}" y="{y + 4}" class="effect-text" font-weight="bold">{effect_text}</text>
            </g>
        '''

    def _x_axis(
        self,
        x_min: float,
        x_max: float,
        plot_width: float,
        height: int,
    ) -> str:
        """Generate x-axis with labels."""
        c = self.config
        y_axis = height - c.margin_bottom + 20

        # Axis line
        parts = [f'''
            <line x1="{c.margin_left}" y1="{y_axis - 10}"
                  x2="{c.margin_left + plot_width}" y2="{y_axis - 10}"
                  class="axis-line"/>
        ''']

        # Tick marks and labels
        if c.log_scale:
            ticks = [0.1, 0.2, 0.5, 1, 2, 5, 10]
        else:
            step = (x_max - x_min) / 5
            ticks = [x_min + i * step for i in range(6)]

        for tick in ticks:
            if x_min <= tick <= x_max:
                x = self._value_to_x(tick, x_min, x_max, plot_width)
                label = f"{tick:.2g}" if tick < 1 else f"{tick:.1f}"
                parts.append(f'''
                    <line x1="{c.margin_left + x}" y1="{y_axis - 10}"
                          x2="{c.margin_left + x}" y2="{y_axis - 5}"
                          class="axis-line"/>
                    <text x="{c.margin_left + x}" y="{y_axis + 5}" class="axis-label" text-anchor="middle">{label}</text>
                ''')

        # Favors labels
        mid_left = c.margin_left + plot_width * 0.25
        mid_right = c.margin_left + plot_width * 0.75
        parts.append(f'''
            <text x="{mid_left}" y="{y_axis + 25}" class="axis-label" text-anchor="middle">← {html.escape(c.favors_left)}</text>
            <text x="{mid_right}" y="{y_axis + 25}" class="axis-label" text-anchor="middle">{html.escape(c.favors_right)} →</text>
        ''')

        return "\n".join(parts)

    def _grid_lines(
        self,
        x_min: float,
        x_max: float,
        plot_width: float,
        height: int,
    ) -> str:
        """Generate background grid lines."""
        c = self.config
        parts = []

        if c.log_scale:
            ticks = [0.1, 0.2, 0.5, 1, 2, 5, 10]
        else:
            step = (x_max - x_min) / 5
            ticks = [x_min + i * step for i in range(6)]

        for tick in ticks:
            if x_min <= tick <= x_max and tick != c.null_value:
                x = self._value_to_x(tick, x_min, x_max, plot_width)
                parts.append(f'''
                    <line x1="{c.margin_left + x}" y1="{c.margin_top + c.height_per_study}"
                          x2="{c.margin_left + x}" y2="{height - c.margin_bottom}"
                          class="grid-line"/>
                ''')

        return "\n".join(parts)

    def _calculate_x_range(
        self,
        studies: List[StudyData],
        pooled: Optional[PooledEstimate],
    ) -> tuple[float, float]:
        """Calculate x-axis range from data."""
        c = self.config

        if c.x_min is not None and c.x_max is not None:
            return c.x_min, c.x_max

        # Collect all values
        values = []
        for study in studies:
            values.extend([study.effect_size, study.lower_ci, study.upper_ci])
        if pooled:
            values.extend([pooled.effect_size, pooled.lower_ci, pooled.upper_ci])

        if c.log_scale:
            # For log scale, ensure positive values
            values = [max(0.01, v) for v in values]
            log_values = [math.log10(v) for v in values]
            log_min = min(log_values) - 0.1
            log_max = max(log_values) + 0.1
            return 10 ** log_min, 10 ** log_max
        else:
            val_min = min(values)
            val_max = max(values)
            margin = (val_max - val_min) * 0.1
            return val_min - margin, val_max + margin

    def _value_to_x(
        self,
        value: float,
        x_min: float,
        x_max: float,
        plot_width: float,
    ) -> float:
        """Convert effect size value to x coordinate."""
        c = self.config

        if c.log_scale:
            # Log scale transformation
            value = max(0.01, value)
            x_min = max(0.01, x_min)
            log_val = math.log10(value)
            log_min = math.log10(x_min)
            log_max = math.log10(x_max)
            return plot_width * (log_val - log_min) / (log_max - log_min)
        else:
            return plot_width * (value - x_min) / (x_max - x_min)

    def _empty_plot_svg(self, title: str) -> str:
        """Generate empty plot with message."""
        c = self.config
        return f'''
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {c.width} {c.min_height}"
            width="{c.width}" height="{c.min_height}">
            <text x="{c.width / 2}" y="25" text-anchor="middle"
                  font-family="{c.font_family}" font-size="{c.title_font_size}px" font-weight="bold">{html.escape(title)}</text>
            <text x="{c.width / 2}" y="{c.min_height / 2}" text-anchor="middle"
                  font-family="{c.font_family}" font-size="{c.font_size}px" fill="#6b7280">No studies to display</text>
        </svg>
        '''


def generate_forest_plot_from_claims(
    claims: List[dict],
    title: str = "Forest Plot",
    config: Optional[ForestPlotConfig] = None,
) -> str:
    """
    Generate forest plot from claim data.

    Args:
        claims: List of claim dictionaries with effect sizes
        title: Plot title
        config: Optional plot configuration

    Returns:
        SVG string
    """
    generator = ForestPlotGenerator(config)

    # Convert claims to StudyData
    studies = []
    pooled = None

    for claim in claims:
        claim_type = claim.get("claim_type", "")

        # Check if this is a pooled estimate
        if claim_type in ("pooled_effect", "POOLED_EFFECT") or claim.get("is_pooled", False):
            pooled = PooledEstimate(
                effect_size=claim["value"],
                lower_ci=claim.get("lower_bound", claim["value"]),
                upper_ci=claim.get("upper_bound", claim["value"]),
                model=claim.get("model", "random"),
                i_squared=claim.get("i_squared"),
                tau_squared=claim.get("tau_squared"),
            )
        else:
            # Individual study
            studies.append(StudyData(
                study_id=claim.get("claim_id", f"study_{len(studies)}"),
                study_label=claim.get("study_label", claim.get("claim_id", f"Study {len(studies) + 1}")),
                effect_size=claim["value"],
                lower_ci=claim.get("lower_bound", claim["value"]),
                upper_ci=claim.get("upper_bound", claim["value"]),
                weight=claim.get("weight", 0),
                n_total=claim.get("sample_size"),
            ))

    return generator.generate(studies, pooled, title)
