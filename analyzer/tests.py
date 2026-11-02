import json
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import MarketReport
from .services import (
    SCRAPING_FALLBACK,
    _validate_analysis,
    analyze_market_trends,
    fetch_market_data,
    process_market_report,
)


class MarketAnalysisTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="testpass123")
        self.client.login(username="tester", password="testpass123")
        self.report = MarketReport.objects.create(
            query="Example market",
            raw_scraped_data="Several companies reported steady market growth.",
            owner=self.user,
        )

    @override_settings(GROQ_API_KEY="test-api-key", GROQ_MODEL="openai/gpt-oss-20b")
    @patch("analyzer.services.Groq")
    def test_analysis_saves_valid_sentiment_and_swot(self, groq_client):
        response_content = " \n" + json.dumps(
            {
                "sentiment_score": "Positive",
                "swot": {
                    "strengths": ["Strong demand"],
                    "weaknesses": [],
                    "opportunities": ["New customer segments"],
                    "threats": ["Growing competition"],
                },
                "media": [
                    {
                        "type": "image",
                        "title": "Enterprise technology workspace",
                        "url": "https://images.unsplash.com/photo-1497366216548-37526070297c?auto=format&fit=crop&w=1200&q=80",
                    },
                    {
                        "type": "document",
                        "title": "Market briefing",
                        "url": "/downloads/example-market-brief.pdf",
                    },
                ],
            }
        ) + "\n "
        groq_client.return_value.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=response_content))]
        )

        result = analyze_market_trends(self.report.pk)

        self.assertEqual(result.status, MarketReport.Status.COMPLETED)
        self.assertEqual(result.sentiment_score, "Positive")
        self.assertEqual(result.swot_json["strengths"], ["Strong demand"])
        self.assertEqual(len(result.swot_json["media"]), 2)
        completion_request = (
            groq_client.return_value.chat.completions.create.call_args.kwargs
        )
        self.assertIn(
            "Return ONLY a valid JSON string.",
            completion_request["messages"][0]["content"],
        )
        self.assertIn(
            "do not include triple backticks (```)",
            completion_request["messages"][0]["content"],
        )
        self.assertEqual(completion_request["model"], "openai/gpt-oss-20b")

    @override_settings(GROQ_API_KEY="test-api-key", GROQ_MODEL="openai/gpt-oss-20b")
    @patch("analyzer.services.Groq")
    def test_invalid_analysis_marks_report_failed(self, groq_client):
        groq_client.return_value.chat.completions.create.return_value = MagicMock(
            choices=[
                MagicMock(message=MagicMock(content='{"unexpected": true}'))
            ]
        )

        with self.assertLogs("analyzer.services", level="ERROR"):
            with self.assertRaises(ValueError):
                analyze_market_trends(self.report.pk)

        self.report.refresh_from_db()
        self.assertEqual(self.report.status, MarketReport.Status.FAILED)

    def test_dashboard_renders_and_create_view_starts_worker(self):
        dashboard_response = self.client.get(reverse("analyzer:dashboard"))
        self.assertEqual(dashboard_response.status_code, 200)

        with patch("analyzer.views.threading.Thread") as thread_class:
            response = self.client.post(
                reverse("analyzer:create-report"),
                {"query": "Another market"},
            )

        created_report = MarketReport.objects.get(query="Another market")
        self.assertEqual(created_report.owner, self.user)
        self.assertRedirects(
            response,
            reverse("analyzer:report-detail", args=[created_report.pk]),
        )
        thread_class.return_value.start.assert_called_once()

    @override_settings(IS_VERCEL=True)
    @patch("analyzer.views.threading.Thread")
    @patch("analyzer.views.process_market_report")
    def test_vercel_report_processing_runs_before_serverless_response(
        self, process_report, thread_class
    ):
        response = self.client.post(
            reverse("analyzer:create-report"),
            {"query": "Serverless market"},
        )

        report = MarketReport.objects.get(query="Serverless market")
        self.assertRedirects(
            response,
            reverse("analyzer:report-detail", args=[report.pk]),
        )
        process_report.assert_called_once_with(report.pk)
        thread_class.assert_not_called()

    def test_analysis_rejects_an_invalid_swot_structure(self):
        with self.assertRaises(ValueError):
            _validate_analysis(
                {
                    "sentiment_score": "Neutral",
                    "swot": {"strengths": []},
                }
            )

    def test_analysis_rejects_unsafe_media_urls(self):
        payload = {
            "sentiment_score": "Neutral",
            "swot": {
                "strengths": [],
                "weaknesses": [],
                "opportunities": [],
                "threats": [],
            },
            "media": [
                {
                    "type": "document",
                    "title": "Untrusted document",
                    "url": "javascript:alert(1)",
                }
            ],
        }

        with self.assertRaisesRegex(ValueError, "safe relative"):
            _validate_analysis(payload)

    @patch("analyzer.services.requests.get")
    def test_market_data_fetch_extracts_search_results(self, request_get):
        request_get.return_value.text = (
            '<div class="result">'
            '<a class="result__a" href="https://example.com/">Example company</a>'
            '<a class="result__snippet">Market growth report</a>'
            "</div>"
        )

        result = fetch_market_data("Example company")

        self.assertIn("Title: Example company", result)
        self.assertIn("Summary: Market growth report", result)
        request_get.return_value.raise_for_status.assert_called_once()

    @override_settings(GROQ_API_KEY="test-api-key", GROQ_MODEL="openai/gpt-oss-20b")
    @patch("analyzer.services.Groq")
    @patch("analyzer.services.fetch_market_data", side_effect=RuntimeError("search unavailable"))
    def test_scraping_failure_uses_fallback_and_completes_analysis(
        self, fetch_market_data_mock, groq_client
    ):
        response_content = json.dumps(
            {
                "sentiment_score": "Neutral",
                "swot": {
                    "strengths": [],
                    "weaknesses": [],
                    "opportunities": [],
                    "threats": [],
                },
                "media": [],
            }
        )
        groq_client.return_value.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=response_content))]
        )

        with self.assertLogs("analyzer.services", level="ERROR") as log_context:
            result = process_market_report(self.report.pk)

        self.assertEqual(result.status, MarketReport.Status.COMPLETED)
        self.assertEqual(result.raw_scraped_data, SCRAPING_FALLBACK)
        self.assertTrue(
            any("search unavailable" in message for message in log_context.output)
        )
        fetch_market_data_mock.assert_called_once_with(self.report.query)

    @override_settings(GROQ_API_KEY="test-api-key", GROQ_MODEL="openai/gpt-oss-20b")
    @patch("analyzer.services.Groq")
    def test_groq_request_failure_is_logged_and_marks_report_failed(
        self, groq_client
    ):
        groq_client.return_value.chat.completions.create.side_effect = RuntimeError(
            "upstream timeout"
        )

        with self.assertLogs("analyzer.services", level="ERROR") as log_context:
            with self.assertRaisesRegex(RuntimeError, "upstream timeout"):
                analyze_market_trends(self.report.pk)

        self.report.refresh_from_db()
        self.assertEqual(self.report.status, MarketReport.Status.FAILED)
        self.assertTrue(
            any("upstream timeout" in message for message in log_context.output)
        )

    def test_dashboard_and_detail_templates_include_styled_layouts(self):
        dashboard_response = self.client.get(reverse("analyzer:dashboard"))
        self.assertContains(dashboard_response, "cdn.tailwindcss.com")
        self.assertContains(dashboard_response, "SignalScope")
        self.assertContains(dashboard_response, "Recent reports")

        self.report.status = MarketReport.Status.COMPLETED
        self.report.swot_json = {
            "strengths": ["Strong demand"],
            "weaknesses": ["Limited distribution"],
            "opportunities": ["New customer segment"],
            "threats": ["New competitors"],
            "media": [],
        }
        self.report.sentiment_score = "Positive"
        self.report.save()

        detail_response = self.client.get(
            reverse("analyzer:report-detail", args=[self.report.pk])
        )
        self.assertContains(detail_response, "cdn.tailwindcss.com")
        self.assertContains(detail_response, "SignalScope")
        self.assertContains(detail_response, "Market intelligence report")
        self.assertContains(detail_response, "SWOT analysis")
        self.assertContains(detail_response, "Professional Analysis")

    def test_anonymous_user_is_redirected_to_login_for_protected_views(self):
        self.client.logout()
        protected_urls = [
            reverse("analyzer:dashboard"),
            reverse("analyzer:report-detail", args=[self.report.pk]),
            reverse("analyzer:download_report_doc", args=[self.report.pk]),
        ]
        for url in protected_urls:
            response = self.client.get(url)
            self.assertRedirects(
                response,
                f"{reverse('login')}?next={url}",
                fetch_redirect_response=False,
            )

    def test_anonymous_post_to_create_report_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.post(
            reverse("analyzer:create-report"), {"query": "Another market"}
        )
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('analyzer:create-report')}",
            fetch_redirect_response=False,
        )

    def test_registration_requires_age_confirmation_checkbox(self):
        self.client.logout()
        response = self.client.post(
            reverse("analyzer:register"),
            {
                "username": "newuser",
                "password1": "StrongPassword123!",
                "password2": "StrongPassword123!",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "This field is required", status_code=400)
        self.assertFalse(User.objects.filter(username="newuser").exists())

    def test_registration_logs_user_in(self):
        self.client.logout()
        response = self.client.post(
            reverse("analyzer:register"),
            {
                "username": "newuser",
                "password1": "StrongPassword123!",
                "password2": "StrongPassword123!",
                "age_confirmed": "on",
            },
        )
        self.assertRedirects(response, reverse("analyzer:dashboard"))
        self.assertTrue(User.objects.filter(username="newuser").exists())
        self.assertTrue(self.client.session.get("_auth_user_id"))

    def test_login_and_logout_work(self):
        self.client.logout()
        login_response = self.client.post(
            reverse("login"),
            {"username": "tester", "password": "testpass123"},
        )
        self.assertRedirects(login_response, reverse("analyzer:dashboard"))

        logout_response = self.client.post(reverse("logout"))
        self.assertRedirects(logout_response, reverse("login"))

    def test_authenticated_user_can_download_report_document(self):
        self.report.status = MarketReport.Status.COMPLETED
        self.report.sentiment_score = "Positive"
        self.report.swot_json = {
            "strengths": ["Strong demand"],
            "weaknesses": ["Limited distribution"],
            "opportunities": ["New customer segment"],
            "threats": ["New competitors"],
            "media": [],
        }
        self.report.save()

        response = self.client.get(
            reverse("analyzer:download_report_doc", args=[self.report.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn("intelligence-report.txt", response["Content-Disposition"])
        content = response.content.decode("utf-8")
        self.assertIn("Query: Example market", content)
        self.assertIn("Sentiment: Positive", content)
        self.assertIn("STRENGTHS", content)
        self.assertIn("Strong demand", content)
        self.assertIn("Google Search:", content)
        self.assertIn("q=Example+market+market+analysis", content.replace(" ", "+"))

    def test_download_filename_is_safe(self):
        self.report.query = "Unsafe / weird: query name!"
        self.report.save()

        response = self.client.get(
            reverse("analyzer:download_report_doc", args=[self.report.pk])
        )
        self.assertEqual(response.status_code, 200)
        filename_part = response["Content-Disposition"]
        self.assertNotIn("/", filename_part.split("filename=")[-1])
        self.assertTrue(filename_part.endswith('.txt"'))

    def test_reports_are_private_to_their_authenticated_owner(self):
        User.objects.create_user(username="other", password="testpass123")
        self.client.logout()
        self.client.login(username="other", password="testpass123")

        detail_response = self.client.get(
            reverse("analyzer:report-detail", args=[self.report.pk])
        )
        download_response = self.client.get(
            reverse("analyzer:download_report_doc", args=[self.report.pk])
        )
        dashboard_response = self.client.get(reverse("analyzer:dashboard"))

        self.assertEqual(detail_response.status_code, 404)
        self.assertEqual(download_response.status_code, 404)
        self.assertNotContains(dashboard_response, "Example market")
