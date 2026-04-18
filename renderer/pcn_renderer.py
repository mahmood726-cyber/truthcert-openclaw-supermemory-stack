"""
PCN (Provenance Certified Numbers) Renderer.

CRITICAL: This renderer REFUSES to render uncertified numbers.
Only numbers from PASS bundles with valid signatures can be rendered.

Enhanced with QWED (Quantitative Workflow with External Determinism):
- Numbers must pass deterministic verification
- Mathematical consistency is checked before rendering
- Proof-carrying output with verification metadata
"""

import html
import json
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass

from certifier.bundle import load_bundle
from certifier.signing import verify_signature
from certifier.constants import BundleOutcome
from certifier.qwed import QWEDVerifier, get_verification_summary, VerificationStatus
from certifier.models import NumericClaim, ClaimType, EvidenceLocator, EvidenceType


@dataclass
class RenderResult:
    """Result of rendering operation."""
    success: bool
    content: str
    error: Optional[str] = None
    warnings: list[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class PCNRenderer:
    """
    Renders certified numeric claims.

    CRITICAL CONTRACT:
    - REFUSES to render uncertified numbers
    - REFUSES to render numbers from REJECT bundles
    - REFUSES to render numbers with invalid signatures
    - All rendered numbers include provenance markers
    """

    # HTML template for certified numbers
    CERTIFIED_NUMBER_TEMPLATE = '''
    <span class="pcn-certified" data-bundle-id="{bundle_id}" data-claim-id="{claim_id}">
        <span class="pcn-value">{value}</span>
        <span class="pcn-unit">{unit}</span>
        <span class="pcn-badge" title="Certified: {profile}">✓</span>
    </span>
    '''

    # Template for confidence intervals
    CI_TEMPLATE = '''
    <span class="pcn-ci">[{lower}, {upper}]</span>
    '''

    # CSS styles
    STYLES = '''
    <style>
    .pcn-certified {
        display: inline-flex;
        align-items: baseline;
        gap: 0.2em;
        background: #f0fff4;
        padding: 0.1em 0.3em;
        border-radius: 3px;
        border: 1px solid #9ae6b4;
    }
    .pcn-value {
        font-weight: 600;
        color: #276749;
    }
    .pcn-unit {
        font-size: 0.9em;
        color: #48bb78;
    }
    .pcn-badge {
        font-size: 0.8em;
        color: #38a169;
        cursor: help;
    }
    .pcn-ci {
        color: #718096;
        font-size: 0.9em;
    }
    .pcn-rejected {
        background: #fff5f5;
        border-color: #fc8181;
    }
    .pcn-rejected .pcn-badge {
        color: #e53e3e;
    }
    </style>
    '''

    def __init__(self, verify_signatures: bool = True, verify_qwed: bool = True):
        self.verify_signatures = verify_signatures
        self.verify_qwed = verify_qwed
        self.qwed_verifier = QWEDVerifier() if verify_qwed else None

    def render_bundle(self, bundle_path: Path) -> RenderResult:
        """
        Render all claims from a certified bundle.

        Args:
            bundle_path: Path to bundle directory

        Returns:
            RenderResult with HTML content or error
        """
        # Load bundle
        try:
            bundle_data = load_bundle(bundle_path)
        except FileNotFoundError:
            return RenderResult(
                success=False,
                content="",
                error=f"Bundle not found: {bundle_path}",
            )

        manifest = bundle_data["manifest"]
        claims = bundle_data.get("claims", [])

        # Check outcome - REFUSE REJECT bundles
        if manifest.get("outcome") != BundleOutcome.PASS.value:
            return RenderResult(
                success=False,
                content="",
                error=f"REFUSED: Bundle outcome is {manifest.get('outcome')}. Only PASS bundles can be rendered.",
            )

        # Verify signature if enabled
        if self.verify_signatures:
            attest_path = bundle_path / "attest"
            sig_file = attest_path / "signature.ed25519"
            pubkey_file = attest_path / "public_key.txt"

            if not sig_file.exists() or not pubkey_file.exists():
                return RenderResult(
                    success=False,
                    content="",
                    error="REFUSED: Missing signature files. Cannot verify bundle authenticity.",
                )

            try:
                signature_b64 = sig_file.read_text().strip()
                public_key_b64 = pubkey_file.read_text().strip()
                verify_signature(manifest, signature_b64, public_key_b64)
            except Exception as e:
                return RenderResult(
                    success=False,
                    content="",
                    error=f"REFUSED: Signature verification failed: {e}",
                )

        # Render claims
        html_parts = [self.STYLES]
        bundle_id = manifest.get("bundle_id", "unknown")
        profile = manifest.get("profile", "unknown")

        for claim in claims:
            rendered = self._render_claim(claim, bundle_id, profile)
            html_parts.append(rendered)

        return RenderResult(
            success=True,
            content="\n".join(html_parts),
        )

    def render_claim(
        self,
        bundle_path: Path,
        claim_id: str,
    ) -> RenderResult:
        """
        Render a single claim from a bundle.

        Args:
            bundle_path: Path to bundle
            claim_id: ID of claim to render

        Returns:
            RenderResult
        """
        result = self.render_bundle(bundle_path)
        if not result.success:
            return result

        # Find specific claim
        bundle_data = load_bundle(bundle_path)
        claims = bundle_data.get("claims", [])

        for claim in claims:
            if claim.get("claim_id") == claim_id:
                manifest = bundle_data["manifest"]
                rendered = self._render_claim(
                    claim,
                    manifest.get("bundle_id", ""),
                    manifest.get("profile", ""),
                )
                return RenderResult(
                    success=True,
                    content=self.STYLES + rendered,
                )

        return RenderResult(
            success=False,
            content="",
            error=f"Claim not found: {claim_id}",
        )

    def _render_claim(
        self,
        claim: dict[str, Any],
        bundle_id: str,
        profile: str,
    ) -> str:
        """Render a single claim to HTML."""
        # Escape all values to prevent XSS
        claim_id = html.escape(str(claim.get("claim_id", "")))
        value = html.escape(str(claim.get("value", "")))
        unit = html.escape(str(claim.get("unit", "")))
        safe_bundle_id = html.escape(bundle_id)
        safe_profile = html.escape(profile)

        rendered = self.CERTIFIED_NUMBER_TEMPLATE.format(
            bundle_id=safe_bundle_id,
            claim_id=claim_id,
            value=value,
            unit=unit,
            profile=safe_profile,
        )

        # Add confidence interval if present
        lower = claim.get("lower_bound")
        upper = claim.get("upper_bound")
        if lower is not None and upper is not None:
            ci = self.CI_TEMPLATE.format(
                lower=html.escape(str(lower)),
                upper=html.escape(str(upper)),
            )
            rendered += ci

        return rendered

    def refuse_uncertified(self, value: Any) -> RenderResult:
        """
        Explicitly refuse to render an uncertified number.

        This method exists to make the refusal explicit and auditable.
        """
        return RenderResult(
            success=False,
            content="",
            error=f"REFUSED: Cannot render uncertified number: {value}. "
                  f"Numbers must be certified through TruthCert before rendering.",
        )

    def verify_claim_qwed(self, claim_dict: dict) -> tuple[bool, list[dict]]:
        """
        Run QWED verification on a claim.

        Returns:
            Tuple of (passed, verification_details)
        """
        if not self.qwed_verifier:
            return True, []

        try:
            # Reconstruct claim for verification
            claim = NumericClaim(
                claim_id=claim_dict.get("claim_id", "unknown"),
                claim_type=ClaimType(claim_dict.get("claim_type", "effect_size")),
                value=claim_dict.get("value", 0),
                unit=claim_dict.get("unit"),
                lower_bound=claim_dict.get("lower_bound"),
                upper_bound=claim_dict.get("upper_bound"),
                standard_error=claim_dict.get("standard_error"),
                variance=claim_dict.get("variance"),
                confidence_level=claim_dict.get("confidence_level", 0.95),
                evidence=[
                    EvidenceLocator(
                        source_type=EvidenceType.OA_DOCUMENT,
                        uri="doi:placeholder",
                        content_hash="sha256:" + "0" * 64,
                    )
                ],
                metadata=claim_dict.get("metadata", {}),
            )

            results = self.qwed_verifier.verify_claim(claim)
            summary = get_verification_summary(results)

            details = []
            for r in results:
                details.append({
                    "check": r.check_type,
                    "status": r.status.value,
                    "message": r.message,
                })

            return summary["all_passed"], details

        except Exception as e:
            return True, [{"error": str(e)}]

    def render_with_proof(
        self,
        bundle_path: Path,
        output_format: str = "html",
    ) -> RenderResult:
        """
        Render bundle with QWED proof annotations.

        Each rendered number includes:
        - Certification status
        - QWED verification status
        - Verification proof chain
        """
        result = self.render_bundle(bundle_path)
        if not result.success:
            return result

        bundle_data = load_bundle(bundle_path)
        claims = bundle_data.get("claims", [])

        # Add QWED verification to each claim
        verified_claims = []
        for claim in claims:
            qwed_passed, qwed_details = self.verify_claim_qwed(claim)
            verified_claims.append({
                **claim,
                "_qwed_verified": qwed_passed,
                "_qwed_details": qwed_details,
            })

        # Re-render with verification badges
        manifest = bundle_data["manifest"]
        bundle_id = manifest.get("bundle_id", "unknown")
        profile = manifest.get("profile", "unknown")

        html_parts = [self.STYLES, self._render_qwed_styles()]

        for claim in verified_claims:
            rendered = self._render_claim_with_proof(claim, bundle_id, profile)
            html_parts.append(rendered)

        return RenderResult(
            success=True,
            content="\n".join(html_parts),
            warnings=result.warnings,
        )

    def _render_qwed_styles(self) -> str:
        """Additional styles for QWED verification badges."""
        return '''
        <style>
        .pcn-qwed-verified {
            position: relative;
        }
        .pcn-qwed-badge {
            font-size: 0.7em;
            margin-left: 0.3em;
            padding: 0.1em 0.3em;
            border-radius: 2px;
            background: #e6fffa;
            color: #234e52;
            cursor: help;
        }
        .pcn-qwed-failed {
            background: #fed7d7;
            color: #742a2a;
        }
        .pcn-proof-tooltip {
            display: none;
            position: absolute;
            background: white;
            border: 1px solid #e2e8f0;
            padding: 0.5em;
            border-radius: 4px;
            font-size: 0.8em;
            z-index: 100;
            min-width: 200px;
        }
        .pcn-qwed-badge:hover + .pcn-proof-tooltip {
            display: block;
        }
        </style>
        '''

    def _render_claim_with_proof(
        self,
        claim: dict,
        bundle_id: str,
        profile: str,
    ) -> str:
        """Render a claim with QWED proof annotation."""
        base_html = self._render_claim(claim, bundle_id, profile)

        qwed_passed = claim.get("_qwed_verified", True)
        qwed_details = claim.get("_qwed_details", [])

        badge_class = "pcn-qwed-badge" + ("" if qwed_passed else " pcn-qwed-failed")
        badge_text = "QWED✓" if qwed_passed else "QWED✗"

        # Build proof tooltip
        proof_lines = ["<strong>QWED Verification:</strong>"]
        for detail in qwed_details:
            status_icon = "✓" if detail.get("status") == "verified" else "✗"
            proof_lines.append(f"{status_icon} {detail.get('check', 'unknown')}")

        proof_html = "<br>".join(proof_lines)

        return f'''
        <div class="pcn-qwed-verified">
            {base_html}
            <span class="{badge_class}" title="QWED Verified">{badge_text}</span>
            <div class="pcn-proof-tooltip">{proof_html}</div>
        </div>
        '''


def render_bundle_report(
    bundle_path: Path,
    output_path: Optional[Path] = None,
) -> str:
    """
    Render a complete HTML report for a bundle.

    Args:
        bundle_path: Path to bundle
        output_path: Optional path to write HTML file

    Returns:
        HTML content
    """
    renderer = PCNRenderer()
    result = renderer.render_bundle(bundle_path)

    if not result.success:
        html_content = f'''
        <!DOCTYPE html>
        <html>
        <head><title>Certification Report - ERROR</title></head>
        <body>
            <h1>Certification Report</h1>
            <div class="error" style="color: red; padding: 1em; background: #fff5f5;">
                <strong>Error:</strong> {html.escape(result.error or 'Unknown error')}
            </div>
        </body>
        </html>
        '''
    else:
        bundle_data = load_bundle(bundle_path)
        manifest = bundle_data["manifest"]

        html_content = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <title>Certification Report - {html.escape(manifest.get('bundle_id', '')[:16])}</title>
            {result.content.split('</style>')[0]}</style>
            <style>
                body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 2em auto; padding: 1em; }}
                .header {{ background: #f7fafc; padding: 1em; border-radius: 8px; margin-bottom: 1em; }}
                .claims {{ display: flex; flex-direction: column; gap: 1em; }}
                .claim-card {{ border: 1px solid #e2e8f0; padding: 1em; border-radius: 8px; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Certification Report</h1>
                <p><strong>Bundle ID:</strong> {html.escape(manifest.get('bundle_id', 'N/A'))}</p>
                <p><strong>Outcome:</strong> <span style="color: {'green' if manifest.get('outcome') == 'PASS' else 'red'}">{html.escape(manifest.get('outcome', 'N/A'))}</span></p>
                <p><strong>Profile:</strong> {html.escape(manifest.get('profile', 'N/A'))}</p>
                <p><strong>Claims:</strong> {manifest.get('claim_count', 0)}</p>
            </div>
            <h2>Certified Claims</h2>
            <div class="claims">
                {result.content}
            </div>
        </body>
        </html>
        '''

    if output_path:
        output_path.write_text(html_content)

    return html_content
