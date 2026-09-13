from django.urls import path

from . import views

urlpatterns = [
    path("", views.chat_view, name="chat"),
    path("send/", views.send_message, name="chat_send"),
]
