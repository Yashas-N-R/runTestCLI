"""This file intentionally uses an internal codename ("beacon") instead of the
word "recording" anywhere -- title, tags, docstring, and body all say
"beacon". Automatic scanning/matching (title/tags/docstring/body) has no way
to know "beacon" means "recording" for this team. This is exactly the case
`.nltestrc.yml`'s `feature_map` is for -- see the "recording" entry mapping to
`tag:beacon-internal-codename` in ../.nltestrc.yml.
"""

import pytest


@pytest.mark.beacon_internal_codename
def test_beacon_pipeline_emits_heartbeat():
    """Verifies the beacon pipeline emits a heartbeat event every 5 seconds."""
    beacon = object()
    assert beacon is not None
