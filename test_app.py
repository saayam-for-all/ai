# test_app.py
import json
import unittest
from app import app

class TestGroqAPI(unittest.TestCase):
    def setUp(self):
        # Configure the Flask app for testing
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_00_config_loading(self):
        """Test configuration loading from json"""
        import app as app_module
        self.assertIsNotNone(app_module.categories)
        self.assertIsNotNone(app_module.category_prompts)
        self.assertGreater(len(app_module.categories), 0)
        self.assertIn("Banking", app_module.categories)
        self.assertIn("Banking", app_module.category_prompts)
        print("\n[PASSED] Config loader verified. Predefined categories loaded correctly.")

    def test_00b_config_fallback(self):
        """Test configuration loader fallbacks on missing file"""
        import app as app_module
        orig_path = app_module.CONFIG_PATH
        app_module.CONFIG_PATH = "non_existent_config.json"
        try:
            app_module.categories = []
            app_module.category_prompts = {}
            app_module.load_config()
            self.assertGreater(len(app_module.categories), 0)
            self.assertIn("Finance", app_module.categories)
            self.assertIn("Finance", app_module.category_prompts)
            print("\n[PASSED] Config fallback loader verified successfully on missing file.")
        finally:
            app_module.CONFIG_PATH = orig_path
            app_module.load_config()

    def test_01_health_check(self):
        """Test home endpoint returns API is running"""
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get("message"), "API is running")
        print("\n[PASSED] Health check endpoint returned 200 OK and expected body.")

    def test_02_predict_categories(self):
        """Test category prediction endpoint"""
        payload = {
            "subject": "Help with opening a savings account",
            "description": "I want to understand how to open a savings account and what documents are needed."
        }
        response = self.client.post(
            '/predict_categories',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        categories = json.loads(response.data)
        self.assertIsInstance(categories, list)
        self.assertTrue(len(categories) > 0)
        print(f"\n[PASSED] Category prediction returned categories: {categories}")
        
        # Save categories for the next test step (or we can use it in a combined integration test)
        self.__class__.predicted_category = categories[0]

    def test_03_generate_answer(self):
        """Test answer generation endpoint using the predicted category"""
        # Ensure we have a category to test
        category = getattr(self.__class__, 'predicted_category', 'Banking')
        payload = {
            "category": category,
            "subject": "Help with opening a savings account",
            "description": "I want to understand how to open a savings account and what documents are needed."
        }
        response = self.client.post(
            '/generate_answer',
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        answer = json.loads(response.data)
        self.assertIsInstance(answer, str)
        self.assertTrue(len(answer) > 0)
        print(f"\n[PASSED] Answer generation returned an answer for category '{category}'. Snippet:\n---\n{answer[:200]}...\n---")

if __name__ == '__main__':
    unittest.main()
