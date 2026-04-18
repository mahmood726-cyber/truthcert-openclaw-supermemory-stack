"""
PRISMA Flow Diagram Generator

Generates SVG PRISMA 2020 flow diagrams for systematic reviews and meta-analyses.
Tracks studies through identification, screening, eligibility, and inclusion.

Reference: Page MJ, et al. The PRISMA 2020 statement. BMJ 2021;372:n71
"""

import html
from dataclasses import dataclass, field
from typing import Any, Optional, List
from enum import Enum


class ScreeningPhase(str, Enum):
    """PRISMA screening phases."""
    IDENTIFICATION = "identification"
    SCREENING = "screening"
    ELIGIBILITY = "eligibility"
    INCLUDED = "included"


@dataclass
class DatabaseSearch:
    """Records from a database search."""
    database_name: str
    records_identified: int
    date_searched: Optional[str] = None


@dataclass
class OtherSource:
    """Records from other sources."""
    source_name: str
    records_identified: int


@dataclass
class ScreeningRecord:
    """Record of screening decisions."""
    total_screened: int
    excluded: int
    reason_excluded: Optional[str] = None


@dataclass
class EligibilityRecord:
    """Record of eligibility assessment."""
    full_text_assessed: int
    excluded: int
    exclusion_reasons: dict[str, int] = field(default_factory=dict)


@dataclass
class InclusionRecord:
    """Record of included studies."""
    studies_included: int
    reports_included: int
    new_studies: Optional[int] = None  # For updates
    new_reports: Optional[int] = None


@dataclass
class PRISMAFlowData:
    """Complete PRISMA flow data."""
    # Identification
    database_searches: List[DatabaseSearch] = field(default_factory=list)
    register_searches: List[DatabaseSearch] = field(default_factory=list)
    other_sources: List[OtherSource] = field(default_factory=list)

    # Before screening
    duplicates_removed: int = 0
    automation_excluded: int = 0  # Records removed by automation tools

    # Screening
    title_abstract_screened: int = 0
    title_abstract_excluded: int = 0

    # Eligibility
    full_text_sought: int = 0
    full_text_not_retrieved: int = 0
    full_text_not_retrieved_reasons: dict[str, int] = field(default_factory=dict)

    full_text_assessed: int = 0
    full_text_excluded: int = 0
    full_text_exclusion_reasons: dict[str, int] = field(default_factory=dict)

    # Included
    studies_included_review: int = 0
    reports_included_review: int = 0
    studies_included_synthesis: int = 0  # For quantitative synthesis (meta-analysis)

    # For updates
    previous_studies: int = 0
    previous_reports: int = 0

    # Metadata
    review_title: str = "Systematic Review"
    is_update: bool = False


@dataclass
class PRISMAConfig:
    """Configuration for PRISMA diagram appearance."""
    width: int = 900
    height: int = 800
    box_width: int = 200
    box_height: int = 60
    box_radius: int = 5

    # Spacing
    horizontal_gap: int = 80
    vertical_gap: int = 40

    # Styling
    font_family: str = "Arial, sans-serif"
    font_size: int = 11
    title_font_size: int = 14

    # Colors
    identification_color: str = "#dbeafe"  # Light blue
    screening_color: str = "#fef3c7"       # Light yellow
    eligibility_color: str = "#d1fae5"     # Light green
    included_color: str = "#e0e7ff"        # Light indigo
    exclusion_color: str = "#fee2e2"       # Light red
    border_color: str = "#374151"
    text_color: str = "#111827"
    arrow_color: str = "#6b7280"


class PRISMAFlowGenerator:
    """
    Generates SVG PRISMA 2020 flow diagrams.

    Following the PRISMA 2020 statement template.
    """

    def __init__(self, config: Optional[PRISMAConfig] = None):
        self.config = config or PRISMAConfig()

    def generate(self, data: PRISMAFlowData) -> str:
        """
        Generate SVG PRISMA flow diagram.

        Args:
            data: PRISMA flow data

        Returns:
            SVG string
        """
        c = self.config

        svg_parts = [self._svg_header()]
        svg_parts.append(self._svg_styles())
        svg_parts.append(self._svg_defs())

        # Title
        svg_parts.append(f'''
            <text x="{c.width / 2}" y="30" class="title" text-anchor="middle">
                PRISMA 2020 Flow Diagram
            </text>
            <text x="{c.width / 2}" y="50" class="subtitle" text-anchor="middle">
                {html.escape(data.review_title)}
            </text>
        ''')

        # Phase labels (left side)
        phases = [
            (120, "Identification"),
            (280, "Screening"),
            (460, "Eligibility"),
            (640, "Included"),
        ]
        for y, label in phases:
            svg_parts.append(f'''
                <text x="20" y="{y}" class="phase-label" writing-mode="vertical-rl"
                      text-orientation="mixed" transform="rotate(180, 20, {y})">{label}</text>
            ''')

        # IDENTIFICATION SECTION
        y_ident = 100

        # Database searches (left column)
        total_database = sum(db.records_identified for db in data.database_searches)
        db_names = ", ".join(db.database_name for db in data.database_searches)
        svg_parts.append(self._box(
            150, y_ident,
            f"Records identified from:\nDatabases (n={total_database})",
            "identification",
            subtitle=db_names[:30] if db_names else None
        ))

        # Register searches
        total_register = sum(db.records_identified for db in data.register_searches)
        if total_register > 0:
            svg_parts.append(self._box(
                150, y_ident + c.box_height + 10,
                f"Registers (n={total_register})",
                "identification"
            ))

        # Other sources (right column)
        total_other = sum(s.records_identified for s in data.other_sources)
        if total_other > 0 or data.previous_studies > 0:
            other_text = "Records identified from:"
            if data.previous_studies > 0:
                other_text += f"\nPrevious studies (n={data.previous_studies})"
            if total_other > 0:
                other_text += f"\nOther sources (n={total_other})"
            svg_parts.append(self._box(
                600, y_ident,
                other_text,
                "identification"
            ))

        # BEFORE SCREENING
        y_before = y_ident + c.box_height + c.vertical_gap + 40

        # Duplicates removed
        svg_parts.append(self._box(
            375, y_before,
            f"Records removed before screening:\nDuplicates (n={data.duplicates_removed})"
            + (f"\nAutomation (n={data.automation_excluded})" if data.automation_excluded else ""),
            "exclusion"
        ))

        # Arrow from identification to before screening
        svg_parts.append(self._arrow(250, y_ident + c.box_height, 375, y_before))
        if total_other > 0:
            svg_parts.append(self._arrow(700, y_ident + c.box_height, 475, y_before))

        # SCREENING SECTION
        y_screen = y_before + c.box_height + c.vertical_gap

        # Records screened
        svg_parts.append(self._box(
            150, y_screen,
            f"Records screened\n(n={data.title_abstract_screened})",
            "screening"
        ))

        # Records excluded
        svg_parts.append(self._box(
            450, y_screen,
            f"Records excluded\n(n={data.title_abstract_excluded})",
            "exclusion"
        ))

        # Arrows
        svg_parts.append(self._arrow(375, y_before + c.box_height, 250, y_screen))
        svg_parts.append(self._arrow(250 + c.box_width, y_screen + c.box_height / 2, 450, y_screen + c.box_height / 2, horizontal=True))

        # ELIGIBILITY SECTION
        y_elig = y_screen + c.box_height + c.vertical_gap

        # Full text sought
        svg_parts.append(self._box(
            150, y_elig,
            f"Reports sought for retrieval\n(n={data.full_text_sought})",
            "eligibility"
        ))

        # Not retrieved
        if data.full_text_not_retrieved > 0:
            reasons = "\n".join(f"{r}: {n}" for r, n in list(data.full_text_not_retrieved_reasons.items())[:3])
            svg_parts.append(self._box(
                450, y_elig,
                f"Reports not retrieved\n(n={data.full_text_not_retrieved})",
                "exclusion",
                subtitle=reasons if reasons else None
            ))
            svg_parts.append(self._arrow(250 + c.box_width, y_elig + c.box_height / 2, 450, y_elig + c.box_height / 2, horizontal=True))

        svg_parts.append(self._arrow(250, y_screen + c.box_height, 250, y_elig))

        # Full text assessed
        y_assess = y_elig + c.box_height + c.vertical_gap

        svg_parts.append(self._box(
            150, y_assess,
            f"Reports assessed for eligibility\n(n={data.full_text_assessed})",
            "eligibility"
        ))

        # Excluded with reasons
        if data.full_text_excluded > 0:
            reasons_text = "\n".join(f"{r}: {n}" for r, n in list(data.full_text_exclusion_reasons.items())[:4])
            svg_parts.append(self._box(
                450, y_assess,
                f"Reports excluded (n={data.full_text_excluded})",
                "exclusion",
                subtitle=reasons_text if reasons_text else None
            ))
            svg_parts.append(self._arrow(250 + c.box_width, y_assess + c.box_height / 2, 450, y_assess + c.box_height / 2, horizontal=True))

        svg_parts.append(self._arrow(250, y_elig + c.box_height, 250, y_assess))

        # INCLUDED SECTION
        y_incl = y_assess + c.box_height + c.vertical_gap

        # Studies in review
        svg_parts.append(self._box(
            150, y_incl,
            f"Studies included in review\n(n={data.studies_included_review})"
            + (f"\nReports (n={data.reports_included_review})" if data.reports_included_review != data.studies_included_review else ""),
            "included"
        ))

        svg_parts.append(self._arrow(250, y_assess + c.box_height, 250, y_incl))

        # Studies in synthesis
        if data.studies_included_synthesis > 0:
            svg_parts.append(self._box(
                450, y_incl,
                f"Studies in quantitative\nsynthesis (meta-analysis)\n(n={data.studies_included_synthesis})",
                "included"
            ))
            svg_parts.append(self._arrow(250 + c.box_width, y_incl + c.box_height / 2, 450, y_incl + c.box_height / 2, horizontal=True))

        svg_parts.append("</svg>")
        return "\n".join(svg_parts)

    def _svg_header(self) -> str:
        """Generate SVG header."""
        c = self.config
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {c.width} {c.height}"
            width="{c.width}" height="{c.height}" class="prisma-flow">'''

    def _svg_styles(self) -> str:
        """Generate SVG styles."""
        c = self.config
        return f'''
        <style>
            .prisma-flow {{
                font-family: {c.font_family};
                font-size: {c.font_size}px;
            }}
            .title {{
                font-size: {c.title_font_size}px;
                font-weight: bold;
                fill: {c.text_color};
            }}
            .subtitle {{
                font-size: {c.font_size}px;
                fill: #6b7280;
            }}
            .phase-label {{
                font-size: {c.font_size + 2}px;
                font-weight: bold;
                fill: #6b7280;
            }}
            .box-text {{
                fill: {c.text_color};
                text-anchor: middle;
                dominant-baseline: central;
            }}
            .box-subtitle {{
                font-size: {c.font_size - 2}px;
                fill: #6b7280;
            }}
            .identification {{ fill: {c.identification_color}; }}
            .screening {{ fill: {c.screening_color}; }}
            .eligibility {{ fill: {c.eligibility_color}; }}
            .included {{ fill: {c.included_color}; }}
            .exclusion {{ fill: {c.exclusion_color}; }}
            .box-border {{
                fill: none;
                stroke: {c.border_color};
                stroke-width: 1;
            }}
            .arrow {{
                fill: none;
                stroke: {c.arrow_color};
                stroke-width: 1.5;
                marker-end: url(#arrowhead);
            }}
        </style>
        '''

    def _svg_defs(self) -> str:
        """Generate SVG definitions (arrowhead)."""
        c = self.config
        return f'''
        <defs>
            <marker id="arrowhead" markerWidth="10" markerHeight="7"
                    refX="9" refY="3.5" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="{c.arrow_color}"/>
            </marker>
        </defs>
        '''

    def _box(
        self,
        x: float,
        y: float,
        text: str,
        box_class: str,
        subtitle: Optional[str] = None,
    ) -> str:
        """Generate a box with text."""
        c = self.config

        # Split text into lines
        lines = text.split("\n")
        line_height = 14

        # Calculate vertical position for centering
        total_height = len(lines) * line_height
        if subtitle:
            total_height += 15  # Extra space for subtitle
        start_y = y + (c.box_height - total_height) / 2 + line_height / 2

        parts = [
            f'<rect x="{x}" y="{y}" width="{c.box_width}" height="{c.box_height}" '
            f'rx="{c.box_radius}" class="{box_class}"/>',
            f'<rect x="{x}" y="{y}" width="{c.box_width}" height="{c.box_height}" '
            f'rx="{c.box_radius}" class="box-border"/>',
        ]

        # Main text lines
        for i, line in enumerate(lines):
            parts.append(
                f'<text x="{x + c.box_width / 2}" y="{start_y + i * line_height}" '
                f'class="box-text">{html.escape(line)}</text>'
            )

        # Subtitle
        if subtitle:
            sub_y = start_y + len(lines) * line_height + 5
            for i, sub_line in enumerate(subtitle.split("\n")[:2]):
                parts.append(
                    f'<text x="{x + c.box_width / 2}" y="{sub_y + i * 12}" '
                    f'class="box-text box-subtitle">{html.escape(sub_line[:30])}</text>'
                )

        return "\n".join(parts)

    def _arrow(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        horizontal: bool = False,
    ) -> str:
        """Generate an arrow between points."""
        if horizontal:
            # Straight horizontal arrow
            return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="arrow"/>'
        else:
            # L-shaped arrow
            mid_y = (y1 + y2) / 2
            return f'<path d="M{x1},{y1} L{x1},{mid_y} L{x2},{mid_y} L{x2},{y2}" class="arrow"/>'


def create_prisma_from_dict(data: dict[str, Any]) -> PRISMAFlowData:
    """
    Create PRISMAFlowData from a dictionary.

    Args:
        data: Dictionary with PRISMA data

    Returns:
        PRISMAFlowData object
    """
    # Parse database searches
    database_searches = []
    for db in data.get("database_searches", []):
        database_searches.append(DatabaseSearch(
            database_name=db.get("name", "Database"),
            records_identified=db.get("records", 0),
            date_searched=db.get("date"),
        ))

    # Parse other sources
    other_sources = []
    for src in data.get("other_sources", []):
        other_sources.append(OtherSource(
            source_name=src.get("name", "Other"),
            records_identified=src.get("records", 0),
        ))

    return PRISMAFlowData(
        database_searches=database_searches,
        other_sources=other_sources,
        duplicates_removed=data.get("duplicates_removed", 0),
        automation_excluded=data.get("automation_excluded", 0),
        title_abstract_screened=data.get("screened", 0),
        title_abstract_excluded=data.get("screened_excluded", 0),
        full_text_sought=data.get("full_text_sought", 0),
        full_text_not_retrieved=data.get("full_text_not_retrieved", 0),
        full_text_not_retrieved_reasons=data.get("not_retrieved_reasons", {}),
        full_text_assessed=data.get("full_text_assessed", 0),
        full_text_excluded=data.get("full_text_excluded", 0),
        full_text_exclusion_reasons=data.get("exclusion_reasons", {}),
        studies_included_review=data.get("studies_included", 0),
        reports_included_review=data.get("reports_included", data.get("studies_included", 0)),
        studies_included_synthesis=data.get("studies_in_synthesis", 0),
        review_title=data.get("title", "Systematic Review"),
    )
