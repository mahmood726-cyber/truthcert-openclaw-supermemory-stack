"""Synthetic malformed responses must not escape as certified objects."""

from unittest.mock import Mock

import pytest

from gateway.openclaw.glue import TruthCertGlue


@pytest.mark.parametrize("payload", [None, [], "SYNTHETIC_PRIVATE_MARKER", 7])
@pytest.mark.parametrize("operation", ["verify_bundle", "submit_job", "get_job_status"])
def test_gateway_refuses_non_object_response(payload, operation):
    with TruthCertGlue(memory_commands=Mock()) as glue:
        response = Mock()
        response.json.return_value = payload
        glue.client.post = Mock(return_value=response)
        glue.client.get = Mock(return_value=response)
        args = () if operation == "submit_job" else ("synthetic-id",)
        with pytest.raises(TypeError, match="Expected an object") as exc:
            getattr(glue, operation)(*args)
        assert "SYNTHETIC_PRIVATE_MARKER" not in str(exc.value)
