from django.test import SimpleTestCase

from apps.ai_assistant.routing import detect_intents


class SemanticRoutingTests(SimpleTestCase):
    def test_synonyms_and_common_misspellings(self):
        cases = {
            "Qui sont les collaborateurs de Genius ?": ("users",),
            "Liste le personnel et leurs rôles": ("users",),
            "Nom de cette organisaton": ("platform",),
            "Quel est mon organisator ?": ("platform",),
            "Montre les matériaux disponibles": ("stock",),
            "J’ai déjà eu à payer combien sur la plateforme ?": ("finance",),
            "Quel montant ai-je déjà réglé ?": ("finance",),
            "Quel est l’avancement des phases ?": ("stages",),
            "Affiche les pièces jointes": ("documents",),
            "Ouvre la galerie": ("photos",),
            "Résume les discussions": ("comments", "report"),
            "Donne un bilan": ("report",),
            "Liste les chantiers": ("projects",),
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(detect_intents(question), expected)

    def test_specific_intent_has_priority_over_scope_word(self):
        self.assertEqual(
            detect_intents("Utilisateurs de l’organisation Genius et leurs rôles"),
            ("users",),
        )
        self.assertEqual(
            detect_intents("Documents du projet Résidence"),
            ("documents",),
        )

    def test_multi_domain_question_selects_each_relevant_domain(self):
        self.assertEqual(
            detect_intents("Compare le stock, les finances et les étapes"),
            ("finance", "stock", "stages"),
        )

    def test_unknown_general_question_does_not_read_business_data(self):
        self.assertEqual(detect_intents("Bonjour, peux-tu m’aider ?"), ())
