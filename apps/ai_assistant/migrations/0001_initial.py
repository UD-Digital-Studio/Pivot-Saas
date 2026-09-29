import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.ai_assistant.models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organizations", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="AssistantConversation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "title",
                    models.CharField(
                        default="Nouvelle conversation", max_length=120, verbose_name="titre"
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("active", "Active"), ("archived", "Archivée")],
                        default="active",
                        max_length=16,
                        verbose_name="statut",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créée le")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="modifiée le")),
                (
                    "archived_at",
                    models.DateTimeField(blank=True, null=True, verbose_name="archivée le"),
                ),
                (
                    "expires_at",
                    models.DateTimeField(
                        db_index=True,
                        default=apps.ai_assistant.models.conversation_expiration,
                        verbose_name="expire le",
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assistant_conversations",
                        to="organizations.organization",
                        verbose_name="organisation",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assistant_conversations",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="utilisateur",
                    ),
                ),
            ],
            options={
                "verbose_name": "conversation avec l’assistant",
                "verbose_name_plural": "conversations avec l’assistant",
                "ordering": ("-updated_at",),
            },
        ),
        migrations.CreateModel(
            name="AssistantMessage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "role",
                    models.CharField(
                        choices=[("user", "Utilisateur"), ("assistant", "Assistant")],
                        max_length=16,
                        verbose_name="rôle",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "En attente"),
                            ("completed", "Terminé"),
                            ("failed", "Échec"),
                        ],
                        default="completed",
                        max_length=16,
                        verbose_name="statut",
                    ),
                ),
                (
                    "content",
                    models.TextField(
                        validators=[
                            django.core.validators.MaxLengthValidator(settings.AI_MESSAGE_MAX_CHARS)
                        ],
                        verbose_name="contenu",
                    ),
                ),
                (
                    "error_code",
                    models.CharField(blank=True, max_length=64, verbose_name="code d’erreur"),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="créé le")),
                (
                    "conversation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="messages",
                        to="ai_assistant.assistantconversation",
                        verbose_name="conversation",
                    ),
                ),
            ],
            options={
                "verbose_name": "message de l’assistant",
                "verbose_name_plural": "messages de l’assistant",
                "ordering": ("created_at", "pk"),
            },
        ),
        migrations.AddIndex(
            model_name="assistantconversation",
            index=models.Index(
                fields=["user", "status", "-updated_at"], name="ai_assistan_user_id_38d6aa_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="assistantmessage",
            index=models.Index(
                fields=["conversation", "created_at"], name="ai_assistan_convers_e1f86d_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="assistantmessage",
            constraint=models.CheckConstraint(
                condition=models.Q(("error_code__gt", ""), ("status", "failed"), _connector="AND")
                | ~models.Q(("status", "failed")),
                name="assistant_failed_message_has_error_code",
            ),
        ),
    ]
