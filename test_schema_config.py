import unittest

from app.models.schema import validate_schema_name


class SchemaConfigurationTestCase(unittest.TestCase):
    def test_valid_schema_identifier_is_accepted(self):
        self.assertEqual(
            validate_schema_name("ireland_dev_saayam_rdbms"),
            "ireland_dev_saayam_rdbms",
        )

    def test_unsafe_schema_identifier_is_rejected(self):
        for value in ("unsafe;drop", "schema-name", "", None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "SQL identifier"):
                    validate_schema_name(value)


if __name__ == "__main__":
    unittest.main()
