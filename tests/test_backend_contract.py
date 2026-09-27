import unittest

from gemini_web2api.backend import (
    BackendCapabilities,
    BackendHealth,
    BackendHealthState,
    BackendRequest,
)
from gemini_web2api.modern import _ModernBackend


class BackendContractTests(unittest.TestCase):
    def test_request_preserves_all_normalized_fields(self):
        request = BackendRequest.from_legacy_args(
            "hello", "model-x", stream=True, files=["/tmp/file"], think_mode=0,
            temporary=True, provider_options={"temperature": 0.2}
        )
        self.assertEqual(request.prompt, "hello")
        self.assertEqual(request.model, "model-x")
        self.assertTrue(request.stream)
        self.assertEqual(request.files, ("/tmp/file",))
        self.assertTrue(request.temporary)
        self.assertEqual(request.provider_options["temperature"], 0.2)

    def test_capability_contract_is_typed_and_serializable(self):
        capabilities = BackendCapabilities(True, True, True, True, True, False)
        self.assertEqual(capabilities.as_dict()["files"], True)
        self.assertFalse(capabilities.as_dict()["provider_options"])

    def test_health_readiness_requires_authentication(self):
        health = BackendHealth(BackendHealthState.READY, initialized=True, authenticated=True)
        self.assertTrue(health.ready)
        degraded = BackendHealth(BackendHealthState.READY, initialized=True, authenticated=False)
        self.assertFalse(degraded.ready)

    def test_modern_backend_exposes_capabilities_and_stopped_health(self):
        backend = _ModernBackend()
        self.assertIsInstance(backend.capabilities, BackendCapabilities)
        self.assertEqual(backend.health().state, BackendHealthState.STOPPED)
        backend.shutdown()
        self.assertEqual(backend.health().state, BackendHealthState.STOPPED)


if __name__ == "__main__":
    unittest.main()
