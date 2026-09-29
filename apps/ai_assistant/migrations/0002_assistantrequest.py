import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("ai_assistant", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="AssistantRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "request_hash",
                    models.CharField(max_length=64, verbose_name="empreinte de requête"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("processing", "En cours"),
                            ("success", "Réussie"),
                            ("failed", "Échec"),
                            ("blocked", "Bloquée"),
                        ],
                        default="processing",
                        max_length=16,
                        verbose_name="statut",
                    ),
                ),
                ("prompt_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("completion_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("total_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("latency_ms", models.PositiveIntegerField(blank=True, null=True)),
                (
                    "error_code",
                    models.CharField(blank=True, max_length=64, verbose_name="code d’erreur"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créée le")),
                (
                    "completed_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="terminée le"),
                ),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="requests",
                        to="ai_assistant.assistantconversation",
                        verbose_name="conversation",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assistant_requests",
                        to="organizations.organization",
                        verbose_name="organisation",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assistant_requests",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "requête vers l’assistant",
                "verbose_name_plural": "requêtes vers l’assistant",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="assistantrequest",
            index=models.Index(
                fields=["user", "-created_at"], name="ai_assistan_user_id_50cff1_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="assistantrequest",
            index=models.Index(
                fields=["request_hash", "-created_at"], name="ai_assistan_request_d97ae5_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="assistantrequest",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "processing")),
                fields=("user",),
                name="one_processing_assistant_request_per_user",
            ),
        ),
    ]
