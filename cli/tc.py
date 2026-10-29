"""
TruthCert CLI - Main command-line interface.

Commands:
  tc plan <input_dir> --policy policies/silver.json
  tc run <job_spec.json>
  tc certify <claims.jsonl> --policy ...
  tc verify <bundle_dir_or_tar>
  tc audit --deep <bundle_dir_or_tar>
  tc pack test
  tc memory remember/recall/forget/wipe/index-codebase/compact/profile
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """TruthCert CLI - Fail-closed certification for numeric claims."""
    pass


# =============================================================================
# Certification Commands
# =============================================================================


@cli.command()
@click.argument("input_dir", type=click.Path(exists=True))
@click.option("--policy", "-p", default="policies/silver.json", help="Policy file path")
@click.option("--output", "-o", default=None, help="Output plan file")
def plan(input_dir: str, policy: str, output: Optional[str]):
    """Plan a certification job from input directory."""
    from datetime import datetime, timezone

    input_path = Path(input_dir)
    policy_path = Path(policy)

    if not policy_path.exists():
        console.print(f"[red]Policy file not found: {policy}[/red]")
        sys.exit(1)

    # Load policy
    with open(policy_path) as f:
        policy_data = json.load(f)

    # Scan input directory
    claims_files = list(input_path.glob("*.jsonl")) + list(input_path.glob("claims*.json"))

    plan_data = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_path.absolute()),
        "policy": policy_data.get("policy_id", policy_path.stem),
        "profile": policy_data.get("profile", "SILVER"),
        "claims_files": [str(f) for f in claims_files],
        "validators": [v["name"] for v in policy_data.get("validators", []) if v.get("enabled", True)],
    }

    # Output plan
    if output:
        with open(output, "w") as f:
            json.dump(plan_data, f, indent=2)
        console.print(f"[green]Plan written to {output}[/green]")
    else:
        console.print(Panel(json.dumps(plan_data, indent=2), title="Certification Plan"))


@cli.command()
@click.argument("job_spec", type=click.Path(exists=True))
def run(job_spec: str):
    """Run a certification job from spec file."""
    import httpx

    with open(job_spec) as f:
        spec = json.load(f)

    # Check if server is running
    base_url = os.environ.get("TRUTHCERT_URL", "http://localhost:8000")

    try:
        response = httpx.post(
            f"{base_url}/jobs",
            json={
                "policy_id": spec.get("policy", "silver"),
                "input_path": spec.get("input_dir"),
                "metadata": spec.get("metadata", {}),
            },
            timeout=30.0,
        )
        response.raise_for_status()
        result = response.json()
        console.print(f"[green]Job submitted: {result['job']['job_id']}[/green]")

    except httpx.ConnectError:
        console.print("[yellow]Server not running. Running locally...[/yellow]")
        # Run locally without server
        _run_local_certification(spec)


def _run_local_certification(spec: dict):
    """Run certification locally without server."""
    from certifier.models import NumericClaim, ScopeLock, Policy, CertificationProfile
    from certifier.bundle import create_bundle
    from certifier.validators import ValidatorRegistry
    from certifier.constants import Severity

    # Load policy
    policy_path = Path(f"policies/{spec.get('policy', 'silver')}.json")
    if not policy_path.exists():
        console.print(f"[red]Policy not found: {policy_path}[/red]")
        return

    with open(policy_path) as f:
        policy_data = json.load(f)
    policy = Policy(**policy_data)

    # Load claims
    claims = []
    input_dir = Path(spec.get("input_dir", "."))
    for claims_file in input_dir.glob("*.jsonl"):
        with open(claims_file) as f:
            for line in f:
                if line.strip():
                    claims.append(NumericClaim(**json.loads(line)))

    if not claims:
        console.print("[red]No claims found in input directory[/red]")
        return

    # Create scope lock
    scope_lock = ScopeLock(
        scope_id="local-run",
        policy_id=policy.policy_id,
        profile=policy.profile,
        required_validators=[v.name for v in policy.validators if v.enabled],
    )

    # Run validation pipeline
    from certifier.models import ValidatorResult, ValidationSummary

    pipeline = ValidatorRegistry.create_pipeline(policy.validators)
    results = []

    with console.status("[bold green]Running validators..."):
        for validator in pipeline:
            result = validator.run(claims, scope_lock, {"policy": policy})
            results.append(result)
            status = "[green]PASS[/green]" if result.passed else f"[red]{result.severity.value}[/red]"
            console.print(f"  {validator.name}: {status}")

    # Summarize
    blocking = [r for r in results if not r.passed and r.severity == Severity.BLOCK]
    warnings = [r for r in results if not r.passed and r.severity == Severity.WARN]

    validation_summary = ValidationSummary(
        results=results,
        all_passed=len(blocking) == 0,
        has_blocking=len(blocking) > 0,
        has_warnings=len(warnings) > 0,
        blocking_count=len(blocking),
        warning_count=len(warnings),
    )

    # Create bundle
    bundle_path, receipt = create_bundle(
        claims=claims,
        scope_lock=scope_lock,
        policy_id=policy.policy_id,
        validation_summary=validation_summary,
        validators=[v.name for v in pipeline],
        sign=True,
    )

    outcome = "PASS" if validation_summary.all_passed else "REJECT"
    color = "green" if outcome == "PASS" else "red"

    console.print(f"\n[{color}]Certification {outcome}[/{color}]")
    console.print(f"Bundle: {bundle_path}")
    console.print(f"Bundle ID: {receipt.get('bundle_id', 'N/A')}")


@cli.command()
@click.argument("claims_file", type=click.Path(exists=True))
@click.option("--policy", "-p", default="silver", help="Policy ID or file path")
@click.option("--output", "-o", default=None, help="Output directory")
def certify(claims_file: str, policy: str, output: Optional[str]):
    """Certify claims from a JSONL file."""
    from certifier.models import NumericClaim

    # Load claims
    claims = []
    with open(claims_file) as f:
        for line in f:
            if line.strip():
                claims.append(NumericClaim(**json.loads(line)))

    console.print(f"Loaded {len(claims)} claims from {claims_file}")

    # Run certification
    spec = {
        "policy": policy.replace(".json", "").replace("policies/", ""),
        "input_dir": str(Path(claims_file).parent),
    }
    _run_local_certification(spec)


@cli.command()
@click.argument("bundle_path", type=click.Path(exists=True))
@click.option("--check-signature/--no-check-signature", default=True)
@click.option("--check-scope-lock/--no-check-scope-lock", default=True)
def verify(bundle_path: str, check_signature: bool, check_scope_lock: bool):
    """Verify a directory or a safely isolated bundle tarball."""
    import tarfile
    from tempfile import TemporaryDirectory

    path = Path(bundle_path)
    if path.suffix != ".gz":
        return _verify_directory(path, check_signature, check_scope_lock)

    # Only our .tar.gz bundle format is supported, not arbitrary gzip files.
    if not path.name.endswith(".tar.gz"):
        raise click.ClickException("Expected a .tar.gz bundle archive")
    with TemporaryDirectory(prefix="truthcert-verify-") as temporary_dir:
        try:
            extracted = _extract_verified_bundle(path, Path(temporary_dir))
            return _verify_directory(extracted, check_signature, check_scope_lock)
        except (OSError, ValueError, tarfile.TarError) as exc:
            raise click.ClickException(f"Unsafe or invalid bundle archive: {exc}") from exc


def _extract_verified_bundle(archive_path: Path, temporary_root: Path) -> Path:
    """Reject escaping, linked, duplicate and oversized archive members before extraction."""
    import tarfile

    expected_name = archive_path.name[:-7]  # remove .tar.gz
    if not expected_name or expected_name in (".", ".."):
        raise ValueError("Invalid bundle directory name")

    total_bytes = 0
    seen = set()
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            entry = member.name.rstrip("/")
            pieces = entry.split("/")
            if (
                entry.startswith(("/", "\\"))
                or "\\" in entry
                or ":" in entry
                or not pieces
                or pieces[0] != expected_name
                or any(piece in ("", ".", "..") for piece in pieces)
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("Archive member escapes bundle or uses an unsafe file type")
            folded = entry.casefold()  # also reject aliases on case-insensitive Windows
            if folded in seen:
                raise ValueError("Duplicate archive member")
            seen.add(folded)
            total_bytes += member.size
            if len(seen) > 1024 or member.size > 50_000_000 or total_bytes > 100_000_000:
                raise ValueError("Bundle archive exceeds conservative extraction limits")

        # Python >=3.11.4 data filter; no symlinks or special members survive
        # the strict preflight, and the fresh temporary directory is isolated.
        archive.extractall(temporary_root, filter="data")

    return temporary_root / expected_name


def _verify_directory(bundle_path: Path, check_signature: bool, check_scope_lock: bool):
    from certifier.bundle import load_bundle
    from certifier.signing import verify_signature
    from certifier.models import ScopeLock

    try:
        bundle_data = load_bundle(bundle_path)
    except FileNotFoundError:
        console.print(f"[red]Bundle not found: {bundle_path}[/red]")
        sys.exit(1)

    manifest = bundle_data["manifest"]
    errors = []
    warnings = []

    # Schema check
    console.print("[bold]Schema validation...[/bold]")
    if manifest.get("bundle_id") and manifest.get("outcome"):
        console.print("  [green]✓ Schema valid[/green]")
    else:
        console.print("  [red]✗ Schema invalid[/red]")
        errors.append("Invalid manifest schema")

    # Signature check
    if check_signature:
        console.print("[bold]Signature verification...[/bold]")
        attest_path = bundle_path / "attest"
        sig_file = attest_path / "signature.ed25519"
        pubkey_file = attest_path / "public_key.txt"

        if sig_file.exists() and pubkey_file.exists():
            try:
                signature_b64 = sig_file.read_text().strip()
                public_key_b64 = pubkey_file.read_text().strip()
                verify_signature(manifest, signature_b64, public_key_b64)
                console.print("  [green]✓ Signature valid[/green]")
            except Exception as e:
                console.print(f"  [red]✗ Signature invalid: {e}[/red]")
                errors.append(str(e))
        else:
            console.print("  [yellow]⚠ No signature files found[/yellow]")
            warnings.append("Missing signature files")

    # Scope lock check
    if check_scope_lock:
        console.print("[bold]Scope lock verification...[/bold]")
        scope_lock_data = bundle_data.get("scope_lock")
        if scope_lock_data:
            scope_lock = ScopeLock(**scope_lock_data)
            computed_hash = scope_lock.compute_hash()
            expected_hash = manifest.get("scope_lock_hash")
            if computed_hash == expected_hash:
                console.print("  [green]✓ Scope lock valid[/green]")
            else:
                console.print("  [red]✗ Scope lock hash mismatch[/red]")
                errors.append("Scope lock hash mismatch")
        else:
            console.print("  [yellow]⚠ No scope lock file[/yellow]")
            warnings.append("Missing scope lock")

    # Summary
    console.print()
    if errors:
        console.print(f"[red]Verification FAILED: {len(errors)} errors[/red]")
        for error in errors:
            console.print(f"  - {error}")
        sys.exit(1)
    else:
        console.print("[green]Verification PASSED[/green]")
        if warnings:
            for warning in warnings:
                console.print(f"  [yellow]Warning: {warning}[/yellow]")


@cli.command()
@click.argument("bundle_path", type=click.Path(exists=True))
@click.option("--deep", is_flag=True, help="Run deep audit")
def audit(bundle_path: str, deep: bool):
    """Run audit on a bundle."""
    from certifier.bundle import load_bundle

    bundle_path = Path(bundle_path)
    bundle_data = load_bundle(bundle_path)

    manifest = bundle_data["manifest"]
    claims = bundle_data.get("claims", [])

    console.print(Panel(f"Auditing bundle: {manifest.get('bundle_id', 'unknown')}", title="Audit"))

    # Basic audit
    table = Table(title="Audit Summary")
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="green")

    table.add_row("Bundle ID", manifest.get("bundle_id", "N/A")[:40] + "...")
    table.add_row("Outcome", manifest.get("outcome", "N/A"))
    table.add_row("Profile", manifest.get("profile", "N/A"))
    table.add_row("Claim Count", str(manifest.get("claim_count", len(claims))))
    table.add_row("Validators", ", ".join(manifest.get("validators", [])))

    console.print(table)

    if deep:
        console.print("\n[bold]Deep Audit[/bold]")
        # Check each claim
        for i, claim in enumerate(claims[:5]):  # Sample first 5
            console.print(f"  Claim {i+1}: {claim.get('claim_id', 'unknown')}")
            if claim.get("evidence"):
                console.print(f"    Evidence: {len(claim['evidence'])} sources")


@cli.group()
def pack():
    """Domain pack commands."""
    pass


@pack.command("test")
def pack_test():
    """Run conformance fixtures for domain packs."""
    console.print("[bold]Running conformance tests...[/bold]")

    # Check for fixtures
    fixtures_dir = Path("examples/fixtures")
    if not fixtures_dir.exists():
        console.print("[yellow]No fixtures directory found[/yellow]")
        return

    # Run basic tests
    tests_passed = 0
    tests_failed = 0

    for fixture in fixtures_dir.glob("*.json"):
        console.print(f"  Testing {fixture.name}...")
        try:
            with open(fixture) as f:
                data = json.load(f)
            # Basic validation
            if "claims" in data or "claim_id" in data:
                console.print(f"    [green]✓ Valid fixture[/green]")
                tests_passed += 1
            else:
                console.print(f"    [yellow]⚠ Missing claims[/yellow]")
                tests_passed += 1
        except Exception as e:
            console.print(f"    [red]✗ Error: {e}[/red]")
            tests_failed += 1

    console.print(f"\n[bold]Results: {tests_passed} passed, {tests_failed} failed[/bold]")


@cli.command()
@click.option("--output", "-o", default="keys", help="Output directory")
def keygen(output: str):
    """Generate Ed25519 keypair."""
    from certifier.signing import save_keypair

    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    private_path = output_dir / "private.key"
    public_path = output_dir / "public.key"

    private_b64, public_b64 = save_keypair(private_path, public_path)

    console.print("[green]Keypair generated:[/green]")
    console.print(f"  Private key: {private_path}")
    console.print(f"  Public key: {public_path}")
    console.print()
    console.print("[yellow]Set environment variables:[/yellow]")
    console.print(f"  export TRUTHCERT_SIGNING_KEY='{private_b64}'")
    console.print(f"  export TRUTHCERT_PUBLIC_KEY='{public_b64}'")


# =============================================================================
# Memory Commands
# =============================================================================


@cli.group()
def memory():
    """Memory subsystem commands."""
    pass


@memory.command("remember")
@click.argument("text")
@click.option("--tags", "-t", default="", help="Comma-separated tags")
@click.option("--type", "memory_type", default="note", type=click.Choice(["note", "decision", "runbook"]))
def memory_remember(text: str, tags: str, memory_type: str):
    """Remember a piece of information."""
    from memory.commands import MemoryCommands

    cmd = MemoryCommands()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    result = cmd.remember(text, tags=tag_list, memory_type=memory_type)

    console.print(f"[green]Remembered:[/green] {result['id']}")
    if result.get("redacted"):
        console.print("[yellow]Note: Some content was redacted[/yellow]")


@memory.command("recall")
@click.argument("query")
@click.option("--pack", is_flag=True, help="Return packed context")
@click.option("--limit", "-n", default=10, help="Maximum results")
def memory_recall(query: str, pack: bool, limit: int):
    """Recall memories matching a query."""
    from memory.commands import MemoryCommands

    cmd = MemoryCommands()
    result = cmd.recall_memories(query, pack=pack, limit=limit)

    if pack:
        console.print(Panel(result["content"], title="Packed Memory Context"))
        console.print(f"Items: {result['items_included']}, Chars: {result['total_chars']}")
    else:
        for item in result["items"]:
            console.print(Panel(
                f"{item['text']}\n\n[dim]Tags: {', '.join(item['tags'])}[/dim]",
                title=f"[{item['type']}] {item['id'][:8]}..."
            ))
        console.print(f"\nTotal matches: {result['total_matches']}")


@memory.command("forget")
@click.option("--id", "item_id", default=None, help="Item ID to forget")
@click.option("--query", "-q", default=None, help="Query to match items")
def memory_forget(item_id: Optional[str], query: Optional[str]):
    """Forget memory items."""
    from memory.commands import MemoryCommands

    if not item_id and not query:
        console.print("[red]Must provide --id or --query[/red]")
        return

    cmd = MemoryCommands()
    result = cmd.forget(item_id=item_id, query=query)

    console.print(f"[green]Removed {result['removed']} items[/green]")


@memory.command("wipe")
@click.option("--yes", is_flag=True, help="Confirm wipe")
def memory_wipe(yes: bool):
    """Wipe all memory data."""
    from memory.commands import MemoryCommands

    if not yes:
        console.print("[yellow]Use --yes to confirm wipe[/yellow]")
        return

    cmd = MemoryCommands()
    result = cmd.wipe(confirm=True)

    if result["wiped"]:
        console.print(f"[green]Wiped {result['items_removed']} items[/green]")
    else:
        console.print("[red]Wipe failed[/red]")


@memory.command("profile")
def memory_profile():
    """Show memory profile and stats."""
    from memory.commands import MemoryCommands

    cmd = MemoryCommands()
    result = cmd.get_profile()

    # Profile settings
    profile = result["profile"]
    table = Table(title="Memory Profile")
    table.add_column("Setting", style="cyan")
    table.add_column("Value")

    table.add_row("Name", profile["name"])
    table.add_row("Auto Recall", str(profile["auto_recall"]))
    table.add_row("Auto Capture", str(profile["auto_capture"]))
    table.add_row("Max Recall Results", str(profile["max_recall_results"]))
    table.add_row("Max Inject Chars", str(profile["max_inject_chars"]))
    table.add_row("Redact Before Store", str(profile["redact_before_store"]))

    console.print(table)

    # Stats
    stats = result["stats"]
    console.print(f"\n[bold]Stats:[/bold]")
    console.print(f"  Total items: {stats['total_items']}")
    console.print(f"  Total bytes: {stats['total_bytes']:,}")
    console.print(f"  By type: {stats['items_by_type']}")


@memory.command("index-codebase")
@click.option("--path", "-p", default=".", help="Path to codebase")
@click.option("--max-files", default=400, help="Maximum files to index")
def memory_index_codebase(path: str, max_files: int):
    """Index a codebase into memory."""
    from memory.commands import MemoryCommands

    cmd = MemoryCommands()

    with console.status("[bold green]Indexing codebase..."):
        result = cmd.index_codebase(path=path, max_files=max_files)

    console.print(f"[green]Indexed codebase:[/green]")
    console.print(f"  Path: {result['repo_path']}")
    console.print(f"  Hash: {result['repo_hash']}")
    console.print(f"  Files: {result['file_count']}")
    console.print(f"  Memory ID: {result['id']}")


@memory.command("compact")
@click.option("--strategy", default="rolling", type=click.Choice(["rolling", "threshold"]))
@click.option("--max-age-days", default=30, help="Max age for rolling strategy")
def memory_compact(strategy: str, max_age_days: int):
    """Compact memory by summarizing old items."""
    from memory.commands import MemoryCommands

    cmd = MemoryCommands()

    with console.status("[bold green]Compacting memory..."):
        result = cmd.compact(strategy=strategy, max_age_days=max_age_days)

    console.print(f"[green]Compaction complete:[/green]")
    console.print(f"  Strategy: {result.get('strategy', strategy)}")
    console.print(f"  Items processed: {result.get('items_processed', 0)}")
    console.print(f"  Summaries created: {result.get('summaries_created', 0)}")
    console.print(f"  Items removed: {result.get('items_removed', 0)}")
    console.print(f"  Deleted cleaned: {result.get('deleted_cleaned', 0)}")


if __name__ == "__main__":
    cli()
