from django.utils.translation import gettext_lazy as _
from django import forms

from .models import OrganizationSubscription, SubscriptionPlan


class SubscriptionPaymentForm(forms.Form):
    plan = forms.ModelChoiceField(queryset=SubscriptionPlan.objects.none())
    billing_cycle = forms.ChoiceField(choices=OrganizationSubscription.BillingCycle.choices)
    operator = forms.ChoiceField(choices=(("MTN", "MTN Mobile Money"), ("ORANGE", "Orange Money")))
    phone = forms.CharField(max_length=20)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = SubscriptionPlan.objects.filter(is_active=True, is_public=True)

    def clean_phone(self):
        value = "".join(character for character in self.cleaned_data["phone"] if character.isdigit() or character == "+")
        if len(value.lstrip("+")) < 9:
            raise forms.ValidationError(_("Saisissez un numéro de téléphone valide."))
        return value

    def clean(self):
        data = super().clean()
        plan = data.get("plan")
        cycle = data.get("billing_cycle")
        if plan and cycle:
            amount = plan.yearly_price if cycle == OrganizationSubscription.BillingCycle.YEARLY else plan.monthly_price
            if amount <= 0:
                self.add_error("plan", "Ce forfait est disponible uniquement sur devis et ne peut pas être payé directement.")
        return data
