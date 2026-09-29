from dataclasses import replace
from unittest.mock import patch

from django.test import SimpleTestCase

from apps.ai_assistant.catalog import (
    CATALOG,
    SENSITIVE_FIELD_NAMES,
    CatalogField,
    catalog_prompt,
    get_entity,
    validate_catalog,
)


class BusinessCatalogTests(SimpleTestCase):
    def test_catalog_matches_current_django_models(self):
        self.assertEqual(validate_catalog(), [])

    def test_sensitive_fields_are_not_exposed(self):
        exposed = {item.name for entity in CATALOG for item in (*entity.fields, *entity.computed)}
        self.assertFalse(exposed & SENSITIVE_FIELD_NAMES)
        rendered = catalog_prompt("fr")
        for sensitive_name in SENSITIVE_FIELD_NAMES:
            self.assertNotIn(sensitive_name, rendered)

    def test_catalog_has_french_and_english_vocabulary(self):
        french = catalog_prompt("fr")
        english = catalog_prompt("en")

        self.assertIn("Projet", french)
        self.assertIn("responsable de chantier", french)
        self.assertIn("Project", english)
        self.assertIn("site manager", english)
        self.assertNotEqual(french, english)

    def test_unknown_entity_is_never_invented(self):
        with self.assertRaisesRegex(KeyError, "Unknown catalog entity"):
            get_entity("fictional_invoice")

    def test_validation_detects_a_removed_or_renamed_model_field(self):
        broken = replace(
            CATALOG[0],
            fields=(*CATALOG[0].fields, CatalogField("missing_field", "absent", "missing")),
        )
        with patch("apps.ai_assistant.catalog.CATALOG", (broken, *CATALOG[1:])):
            errors = validate_catalog()

        self.assertTrue(any("missing_field does not exist" in error for error in errors))

    def test_every_vocabulary_exactly_matches_model_choices(self):
        for entity in CATALOG:
            for field_name, vocabulary in entity.vocabulary.items():
                model_values = {
                    str(value) for value, _label in entity.model._meta.get_field(field_name).choices
                }
                self.assertEqual(model_values, set(vocabulary), f"{entity.key}.{field_name}")
