import logging
import threading
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import MarketReportForm, UserRegistrationForm
from .models import MarketReport
from .services import process_market_report


logger = logging.getLogger(__name__)

SWOT_SECTIONS = (
    ("strengths", "STRENGTHS"),
    ("weaknesses", "WEAKNESSES"),
    ("opportunities", "OPPORTUNITIES"),
    ("threats", "THREATS"),
)


def _render_dashboard(request, form=None, status=200):
    return render(
        request,
        "analyzer/dashboard.html",
        {
            "form": form or MarketReportForm(),
            "reports": MarketReport.objects.filter(owner=request.user)[:25],
        },
        status=status,
    )


def _start_report(request, report):
    if settings.IS_VERCEL:
        try:
            process_market_report(report.pk)
        except Exception:
            logger.exception(
                "Synchronous Vercel processing failed for report %s.",
                report.pk,
            )
            messages.error(
                request,
                "The report could not be completed. Please try again later.",
            )
        else:
            messages.success(request, "Your market report is ready.")
        return redirect("analyzer:report-detail", report_id=report.pk)

    worker = threading.Thread(
        target=process_market_report,
        args=(report.pk,),
        name=f"market-report-{report.pk}",
        daemon=True,
    )

    try:
        worker.start()
    except RuntimeError:
        report.status = MarketReport.Status.FAILED
        report.save(update_fields=["status"])
        logger.exception("Could not start analysis for report %s.", report.pk)
        messages.error(
            request,
            "The report was created, but its analysis could not be started.",
        )
        return redirect("analyzer:report-detail", report_id=report.pk)

    messages.success(request, "Your market report is being prepared.")
    return redirect("analyzer:report-detail", report_id=report.pk)


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.user.is_authenticated:
        return redirect("analyzer:dashboard")

    form = UserRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Your SignalScope account is ready.")
        return redirect("analyzer:dashboard")

    return render(
        request,
        "registration/register.html",
        {"form": form},
        status=400 if request.method == "POST" and not form.is_valid() else 200,
    )


@login_required
@require_GET
def dashboard_view(request):
    return _render_dashboard(request)


@login_required
@require_GET
def report_detail_view(request, report_id):
    report = get_object_or_404(
        MarketReport,
        pk=report_id,
        owner=request.user,
    )
    return render(
        request,
        "analyzer/report_detail.html",
        {"report": report},
    )


@login_required
@require_POST
def create_report_view(request):
    form = MarketReportForm(request.POST)
    if not form.is_valid():
        return _render_dashboard(request, form=form, status=400)

    report = form.save(commit=False)
    report.owner = request.user
    report.save()
    return _start_report(request, report)


def _single_line(value):
    return " ".join(str(value).split())


def _format_report_document(report):
    divider = "=" * 76
    subsection_divider = "-" * 76
    lines = [
        divider,
        "SIGNALSCOPE | MARKET INTELLIGENCE REPORT",
        divider,
        "",
        f"Query: {_single_line(report.query)}",
        f"Sentiment: {_single_line(report.sentiment_score)}",
        f"Status: {report.get_status_display()}",
        f"Created: {report.created_at.isoformat()}",
        "",
        divider,
        "DETAILED SWOT ANALYSIS",
        divider,
    ]

    swot_data = report.swot_json if isinstance(report.swot_json, dict) else {}
    for key, title in SWOT_SECTIONS:
        lines.extend(["", title, subsection_divider])
        findings = swot_data.get(key, [])
        if isinstance(findings, list):
            safe_findings = [
                _single_line(finding)
                for finding in findings
                if isinstance(finding, str) and _single_line(finding)
            ]
        else:
            safe_findings = []

        if safe_findings:
            lines.extend(f"- {finding}" for finding in safe_findings)
        else:
            lines.append("- No findings available.")

    lines.extend(
        [
            "",
            divider,
            "REFERENCE DIRECTORY",
            divider,
            "These links open search and reference indexes for further research.",
            "SignalScope does not host or hotlink external media assets.",
            "",
        ]
    )

    query = _single_line(report.query)
    reference_links = (
        (
            "Google Search",
            "https://www.google.com/search?"
            + urlencode({"q": f"{query} market analysis"}),
        ),
        (
            "Google News",
            "https://news.google.com/search?"
            + urlencode({"q": f"{query} market"}),
        ),
        (
            "Wikipedia",
            "https://en.wikipedia.org/w/index.php?"
            + urlencode({"search": query}),
        ),
    )
    lines.extend(f"{label}: {url}" for label, url in reference_links)
    lines.extend(["", divider, "END OF REPORT", divider, ""])
    return "\n".join(lines)


@login_required
@require_GET
def download_report_doc_view(request, report_id):
    report = get_object_or_404(
        MarketReport,
        pk=report_id,
        owner=request.user,
    )
    response = HttpResponse(
        _format_report_document(report),
        content_type="text/plain; charset=utf-8",
    )
    filename = slugify(report.query)[:60] or f"market-report-{report.pk}"
    response["Content-Disposition"] = (
        f'attachment; filename="{filename}-intelligence-report.txt"'
    )
    return response
