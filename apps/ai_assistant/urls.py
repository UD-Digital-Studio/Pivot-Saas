from django.urls import path

from . import views

app_name = "ai_assistant"

urlpatterns = [
    path("conversation/", views.conversation_panel, name="conversation-panel"),
    path("message/", views.send_message, name="send-message"),
    path("conversation/archiver/", views.archive_current_conversation, name="archive"),
]
