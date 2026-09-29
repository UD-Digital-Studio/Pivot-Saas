from django.shortcuts import get_object_or_404

from .models import AssistantConversation


def conversations_for_user(user, *, include_archived=False):
    queryset = AssistantConversation.objects.filter(user=user).select_related("organization")
    if not include_archived:
        queryset = queryset.filter(status=AssistantConversation.Status.ACTIVE)
    return queryset


def conversation_for_user(user, pk, *, include_archived=False):
    return get_object_or_404(conversations_for_user(user, include_archived=include_archived), pk=pk)
