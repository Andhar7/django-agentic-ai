from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from agents.llm_service import LLMService

from .forms import MessageForm
from .models import Conversation


@login_required
def chat_view(request):
    conversation, _ = Conversation.objects.get_or_create(user=request.user)

    form = MessageForm()

    chat_messages = conversation.messages.all().order_by("created_at")

    return render(
        request,
        "chat/chat.html",
        {"conversation": conversation, "chat_messages": chat_messages, "form": form},
    )


@login_required
@require_POST
def send_message(request):

    conversation, _ = Conversation.objects.get_or_create(user=request.user)
    form = MessageForm(request.POST)

    if form.is_valid():
        user_message = conversation.messages.create(
            role="user",
            content=form.cleaned_data["content"],
        )

        llm = LLMService(model=settings.OLLAMA_MODEL, host=settings.OLLAMA_BASE_URL)
        reply_text = llm.generate(form.cleaned_data["content"])

        assistant_message = conversation.messages.create(
            role="assistant",
            content=reply_text,
            route="llm",
        )

        return render(
            request,
            "chat/partials/message_pair.html",
            {"user_message": user_message, "assistant_message": assistant_message},
        )

    return HttpResponse(status=400)
