import unittest
from types import SimpleNamespace

from gemini_web2api.model_catalog import google_models, openai_models


class ModelCatalogTests(unittest.TestCase):
    def test_openai_catalog_uses_account_model_names(self):
        models = [SimpleNamespace(name="gemini-live-account-model", description="account model")]
        result = openai_models(models)
        self.assertEqual(result[0]["id"], "gemini-live-account-model")
        self.assertEqual(result[0]["description"], "account model")

    def test_google_catalog_uses_account_model_names(self):
        models = [SimpleNamespace(id="model-x", display_name="Model X")]
        result = google_models(models)
        self.assertEqual(result[0]["name"], "models/model-x")
        self.assertEqual(result[0]["displayName"], "model-x")
        self.assertIn("generateContent", result[0]["supportedGenerationMethods"])


if __name__ == "__main__":
    unittest.main()
