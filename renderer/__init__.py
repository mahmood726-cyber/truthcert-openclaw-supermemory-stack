"""
PCN Renderer - Renders certified bundles, refuses uncertified numbers.

Includes:
- PCNRenderer: Core certified number rendering
- ForestPlotGenerator: SVG forest plots for meta-analysis
- PRISMAFlowGenerator: PRISMA 2020 flow diagrams
"""

from .pcn_renderer import PCNRenderer, RenderResult, render_bundle_report
from .forest_plot import ForestPlotGenerator, ForestPlotConfig, StudyData, PooledEstimate, generate_forest_plot_from_claims
from .prisma_flow import PRISMAFlowGenerator, PRISMAConfig, PRISMAFlowData, create_prisma_from_dict

__all__ = [
    # PCN Renderer
    "PCNRenderer",
    "RenderResult",
    "render_bundle_report",
    # Forest Plot
    "ForestPlotGenerator",
    "ForestPlotConfig",
    "StudyData",
    "PooledEstimate",
    "generate_forest_plot_from_claims",
    # PRISMA Flow
    "PRISMAFlowGenerator",
    "PRISMAConfig",
    "PRISMAFlowData",
    "create_prisma_from_dict",
]
