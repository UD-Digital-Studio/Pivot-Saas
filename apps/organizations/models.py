from django.db import models


class Organization(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspendue"
        ARCHIVED = "archived", "Archivée"

    name = models.CharField("nom", max_length=160)
    slug = models.SlugField("identifiant", max_length=180, unique=True)
    status = models.CharField(
        "statut",
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    created_at = models.DateTimeField("créée le", auto_now_add=True)
    updated_at = models.DateTimeField("modifiée le", auto_now=True)

    class Meta:
        ordering = ("name",)
        verbose_name = "organisation"
        verbose_name_plural = "organisations"

    def __str__(self) -> str:
        return self.name
