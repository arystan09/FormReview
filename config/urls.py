from django.urls import path

from formreview.views import liveness

urlpatterns = [path("health/live", liveness, name="health-live")]
