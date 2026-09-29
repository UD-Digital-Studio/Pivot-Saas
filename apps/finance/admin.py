from django.contrib import admin

from .models import ExpenseOwnerDecision, ExpensePivotVerification, ExpenseRequest, ExpenseRequestAttachment, ExpenseRequestTransition, ExpenseTechnicalOpinion, PaymentTransaction, Withdrawal

admin.site.register(PaymentTransaction)
admin.site.register(Withdrawal)
admin.site.register(ExpenseRequest)
admin.site.register(ExpenseRequestTransition)
admin.site.register(ExpenseRequestAttachment)
admin.site.register(ExpenseTechnicalOpinion)
admin.site.register(ExpensePivotVerification)
admin.site.register(ExpenseOwnerDecision)
