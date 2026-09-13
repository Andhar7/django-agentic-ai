from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import MessageForm
from .models import Conversation


@login_required
def chat_view(request):
    conversation, _ = Conversation.objects.get_or_create(user=request.user)
    if request.method == "POST":
        form = MessageForm(request.POST)
        if form.is_valid():
            conversation.messages.create(
                role="user", content=form.cleaned_data["content"]
            )
            conversation.messages.create(
                role="assistant",
                content=f"Echo: {form.cleaned_data['content']}",
                route="echo",
            )
            return redirect("chat")
    else:
        form = MessageForm()

    chat_messages = conversation.messages.all().order_by("created_at")

    return render(
        request,
        "chat/chat.html",
        {"conversation": conversation, "chat_messages": chat_messages, "form": form},
    )
