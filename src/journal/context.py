def roles(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    from .permissions import can_write, is_admin
    from .activity import unseen_count
    from .bugs import BugForm
    from .models import BugReport
    context = {"can_write": can_write(user), "is_admin": is_admin(user), "unseen_count": unseen_count(user),
               "bug_form": BugForm(initial={"page": request.path})}
    if context["is_admin"]:
        context["open_bugs"] = BugReport.objects.filter(status=BugReport.NEW).count()
    return context
