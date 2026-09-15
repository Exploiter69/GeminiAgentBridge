import unittest
from types import SimpleNamespace

from gemini_web2api.model_catalog import google_models, openai_models


class ModelCatalogTests(unittest.TestCase):
    def test_openai_catalog_uses_account_model_names(self):
        models = [SimpleNamespace(model_name="gemini-live-account-model", description="account model", is_available=True)]
        result = openai_models(models)
        self.assertEqual(result[0]["id"], "gemini-live-account-model")
        self.assertEqual(result[0]["description"], "account model")

    def test_google_catalog_uses_account_model_names(self):
        models = [SimpleNamespace(model_name="model-x", display_name="Model X", is_available=True)]
        result = google_models(models)
        self.assertEqual(result[0]["name"], "models/model-x")
        self.assertEqual(result[0]["displayName"], "Model X")
        self.assertIn("generateContent", result[0]["supportedGenerationMethods"])

    def test_unavailable_models_are_not_advertised(self):
        models = [
            SimpleNamespace(model_name="available", is_available=True),
            SimpleNamespace(model_name="unavailable", is_available=False),
        ]
        result = openai_models(models)
        self.assertEqual([item["id"] for item in result], ["available"])


if __name__ == "__main__":
    unittest.main()
