from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from accounts.views import select_workspace
from documents import api
from extraction import api as extraction_api
from extraction import live_api
from formreview.views import liveness
from reviews import api as reviews_api

urlpatterns = [
    path("api/v1/drafts/<uuid:draft_id>", reviews_api.patch_draft),
    path("drafts/<uuid:draft_id>/confirm", reviews_api.confirm),
    path("drafts/<uuid:draft_id>/approve", reviews_api.approve_endpoint),
    path("records/<uuid:record_id>", reviews_api.record),
    path("records/<uuid:record_id>/export", reviews_api.export),
    path("documents/<uuid:document_id>/live-confirm", live_api.live_confirmation),
    path("live-attempts/<uuid:attempt_id>", live_api.attempt_view),
    path("documents/<uuid:document_id>/extractions", extraction_api.extract),
    path("documents/<uuid:document_id>/drafts", extraction_api.draft_create),
    path("api/v1/extractions/<uuid:run_id>", extraction_api.extraction_json),
    path("extractions/<uuid:run_id>", extraction_api.preview),
    path("drafts/<uuid:draft_id>", reviews_api.edit),
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
