from django.urls import path

from . import views


app_name = "analyzer"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("accounts/register/", views.register_view, name="register"),
    path("reports/create/", views.create_report_view, name="create-report"),
    path(
        "report/<int:report_id>/download/",
        views.download_report_doc_view,
        name="download_report_doc",
    ),
    path(
        "reports/<int:report_id>/",
        views.report_detail_view,
        name="report-detail",
    ),
]
