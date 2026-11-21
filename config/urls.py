from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from accounts.views import select_workspace
from documents import api
from formreview.views import liveness

urlpatterns = [
    path("", RedirectView.as_view(url="/accounts/workspaces")),
    path("health/live", liveness, name="health-live"),
    path("health/ready", api.readiness, name="health-ready"),
    path("accounts/login", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/workspaces", select_workspace, name="workspaces"),
    path("api/v1/documents", api.documents_api),
    path("documents", api.inbox, name="inbox"),
    path("documents/<uuid:document_id>", api.source, name="source"),
    path("documents/<uuid:document_id>/text", api.source_text, name="source-text"),
]
