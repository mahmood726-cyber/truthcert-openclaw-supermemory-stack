# TruthCert Test Suite

This directory contains the comprehensive test suite for the TruthCert OpenClaw SuperMemory Stack.

## Test Organization

The test suite is organized by component:

```
tests/
├── conftest.py              # Shared fixtures and test configuration
├── __init__.py              # Package marker
├── test_api.py              # FastAPI endpoint tests
├── test_async_backend.py    # Async SQLite backend tests
├── test_certification.py    # End-to-end certification tests
├── test_fts5_sanitizer.py   # FTS5 query sanitization tests
├── test_gateway.py          # Gateway/glue layer tests
├── test_integration.py      # Integration tests
├── test_job_store.py        # Job store tests
├── test_memory.py           # Memory subsystem tests
├── test_nma_and_qwed.py     # NMA and QWED validator tests
├── test_renderer.py         # Renderer tests
└── test_validators.py       # Validator tests
```

### Test Categories

| File | Description | Key Features |
|------|-------------|--------------|
| `test_api.py` | FastAPI endpoint tests | TestClient, HTTP responses, error codes |
| `test_async_backend.py` | Async SQLite backend | asyncio, concurrent operations, connection pooling |
| `test_certification.py` | Certification workflow | Bundle creation, signature verification |
| `test_gateway.py` | Gateway/glue layer | HTTP mocking, TruthCertGlue class |
| `test_memory.py` | Memory subsystem | Storage, search, redaction |
| `test_validators.py` | Validator tests | All validators, edge cases |

## Running Tests

### Prerequisites

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov httpx

# Or with the full package
pip install -e ".[dev]"
```

### Basic Test Commands

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_api.py

# Run specific test class
pytest tests/test_api.py::TestCertifyEndpoint

# Run specific test
pytest tests/test_api.py::TestCertifyEndpoint::test_certify_valid_claim
```

### Running Async Tests

```bash
# Async tests require pytest-asyncio
pytest tests/test_async_backend.py -v
```

### Running with Coverage

```bash
# Generate coverage report
pytest --cov=certifier --cov=memory --cov=gateway --cov-report=term-missing

# Generate HTML coverage report
pytest --cov=certifier --cov=memory --cov=gateway --cov-report=html
open htmlcov/index.html
```

### Running in Parallel

```bash
# Install pytest-xdist for parallel execution
pip install pytest-xdist

# Run tests in parallel
pytest -n auto
```

## Coverage Requirements

The test suite aims for the following coverage targets:

| Component | Target Coverage |
|-----------|-----------------|
| `certifier/` | >= 80% |
| `memory/` | >= 80% |
| `gateway/` | >= 75% |
| Overall | >= 80% |

## Available Fixtures

Fixtures are defined in `conftest.py` and available to all tests:

### Directory and Environment Fixtures

| Fixture | Description |
|---------|-------------|
| `temp_dir` | Temporary directory for test artifacts |
| `setup_test_env` | Sets up test environment variables (autouse) |

### Signing and Keys

| Fixture | Description |
|---------|-------------|
| `signing_keys` | Generates and sets signing keys for tests |

### Claim and Evidence Fixtures

| Fixture | Description |
|---------|-------------|
| `sample_evidence` | Valid EvidenceLocator |
| `sample_claim` | Valid NumericClaim with evidence |
| `memory_claim` | Claim citing memory (should fail) |

### Policy and Scope Fixtures

| Fixture | Description |
|---------|-------------|
| `sample_scope_lock` | Valid ScopeLock |
| `bronze_policy` | Bronze tier policy |
| `silver_policy` | Silver tier policy |

### Memory Fixtures

| Fixture | Description |
|---------|-------------|
| `memory_db` | Temporary SQLite memory backend |
| `memory_profile` | Test memory profile |
| `sample_memory_item` | Sample MemoryItem |

### Usage Example

```python
def test_with_fixtures(sample_claim, sample_scope_lock, signing_keys, temp_dir):
    """Example test using fixtures."""
    # sample_claim: NumericClaim with valid evidence
    # sample_scope_lock: ScopeLock for silver policy
    # signing_keys: (private_key, public_key) tuple
    # temp_dir: Path to temporary directory

    assert sample_claim.claim_id == "test-claim-001"
    assert sample_scope_lock.policy_id == "silver"
```

## Writing Tests

### Test Naming Convention

- Test files: `test_<component>.py`
- Test classes: `Test<Feature>`
- Test methods: `test_<behavior>`

### Example Test Structure

```python
"""Tests for my component."""

import pytest


class TestMyFeature:
    """Test MyFeature functionality."""

    def test_basic_operation(self, fixture1, fixture2):
        """Test basic operation works correctly."""
        # Arrange
        input_data = {"key": "value"}

        # Act
        result = my_function(input_data)

        # Assert
        assert result is not None
        assert result["status"] == "success"

    def test_error_handling(self):
        """Test error handling."""
        with pytest.raises(ValueError):
            my_function(invalid_input)

    @pytest.mark.asyncio
    async def test_async_operation(self, async_fixture):
        """Test async operation."""
        result = await async_function()
        assert result is not None
```

### Testing API Endpoints

```python
from fastapi.testclient import TestClient
from certifier.main import app

def test_endpoint(signing_keys):
    client = TestClient(app)
    response = client.post("/certify", json={...})
    assert response.status_code == 200
```

### Testing with Mocks

```python
from unittest.mock import patch, MagicMock

def test_with_mock():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"result": "ok"}

    with patch("module.function", return_value=mock_response):
        result = function_under_test()
        assert result["result"] == "ok"
```

### Testing Async Code

```python
import pytest

@pytest.mark.asyncio
async def test_async_function(async_fixture):
    result = await async_function()
    assert result is not None
```

## Test Categories (Markers)

Tests can be categorized with pytest markers:

```python
@pytest.mark.slow
def test_slow_operation():
    ...

@pytest.mark.integration
def test_integration():
    ...
```

Run specific categories:

```bash
# Skip slow tests
pytest -m "not slow"

# Run only integration tests
pytest -m integration
```

## Continuous Integration

The test suite is designed to run in CI environments. Recommended CI configuration:

```yaml
# Example GitHub Actions
test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v3
    - uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    - run: pip install -e ".[dev]"
    - run: pytest --cov --cov-report=xml
    - uses: codecov/codecov-action@v3
```

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure the package is installed in development mode:
   ```bash
   pip install -e .
   ```

2. **Async test failures**: Ensure pytest-asyncio is installed and tests use `@pytest.mark.asyncio`

3. **Fixture not found**: Check that `conftest.py` is in the tests directory

4. **Database lock errors**: Tests may need to use separate temp directories:
   ```python
   def test_concurrent(temp_dir):
       db1 = temp_dir / "db1.db"
       db2 = temp_dir / "db2.db"
   ```

### Debug Mode

```bash
# Run with debug output
pytest -v --tb=long

# Stop on first failure
pytest -x

# Enter debugger on failure
pytest --pdb
```

## Contributing Tests

When adding new features, please:

1. Add corresponding tests in the appropriate test file
2. Ensure all tests pass locally before pushing
3. Maintain or improve coverage levels
4. Add docstrings explaining test purpose
5. Use descriptive test names following the convention

## License

Tests are part of the TruthCert project and share the same license.
