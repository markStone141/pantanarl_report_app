from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment

from .models import Article, ArticleFavorite, ArticleLike, ArticleViewHistory, Product


class TestimonyImportTests(TestCase):
    def test_import_csv_is_idempotent_and_writes_error_file(self):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            products_csv = tmp_path / "products.csv"
            articles_csv = tmp_path / "articles.csv"
            errors_csv = tmp_path / "errors.csv"

            products_csv.write_text(
                "legacy_product_id,name,description\n1,UN,UN desc\n",
                encoding="utf-8",
            )
            articles_csv.write_text(
                "legacy_article_id,title,body,author,video_url,legacy_product_id,testimonied_at,created_at,updated_at\n"
                "100,First,Body,Alice,,1,2026-03-01,2026-03-01T10:00:00+09:00,2026-03-01T10:00:00+09:00\n"
                "101,Bad,Body,Bob,,999,2026-03-01,2026-03-01T10:00:00+09:00,2026-03-01T10:00:00+09:00\n",
                encoding="utf-8",
            )

            call_command(
                "import_articles_csv",
                products=str(products_csv),
                articles=str(articles_csv),
                errors=str(errors_csv),
            )
            call_command(
                "import_articles_csv",
                products=str(products_csv),
                articles=str(articles_csv),
                errors=str(errors_csv),
            )

            self.assertEqual(Product.objects.count(), 1)
            self.assertEqual(Article.objects.count(), 1)
            self.assertTrue(errors_csv.exists())


class TestimonyReactionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="u1", password="pass")
        self.article = Article.objects.create(
            title="Article",
            body="Body",
            author="Author",
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )

    def test_favorite_unique(self):
        ArticleFavorite.objects.create(user=self.user, article=self.article)
        with self.assertRaises(IntegrityError):
            ArticleFavorite.objects.create(user=self.user, article=self.article)

    def test_view_history_increments_on_detail(self):
        self.client.force_login(self.user)
        url = reverse("testimony_article_detail", args=[self.article.id])

        first = self.client.get(url)
        self.assertEqual(first.status_code, 200)
        second = self.client.get(url)
        self.assertEqual(second.status_code, 200)

        history = ArticleViewHistory.objects.get(user=self.user, article=self.article)
        self.assertEqual(history.view_count, 2)
        self.article.refresh_from_db()
        self.assertEqual(self.article.view_count, 2)


class TestimonyLoginTests(TestCase):
    def test_report_user_without_member_can_login(self):
        user = get_user_model().objects.create_user(username="report", password="report-pass")
        response = self.client.post(
            reverse("testimony_login"),
            {"login_id": "report", "password": "report-pass"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("testimony_article_list"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_member_linked_user_can_login(self):
        user = get_user_model().objects.create_user(username="m1", password="pass1")
        Member.objects.create(name="Member1", user=user, is_active=True)
        response = self.client.post(
            reverse("testimony_login"),
            {"login_id": "m1", "password": "pass1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("testimony_article_list"))

    def test_non_member_non_ops_user_is_rejected(self):
        get_user_model().objects.create_user(username="u2", password="pass2")
        response = self.client.post(
            reverse("testimony_login"),
            {"login_id": "u2", "password": "pass2"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "IDまたはパスワードが正しくありません。")


class TestimonyCreatePermissionTests(TestCase):
    def test_non_admin_cannot_open_create_page(self):
        user = get_user_model().objects.create_user(username="report", password="report-pass")
        self.client.force_login(user)
        response = self.client.get(reverse("testimony_article_create"))
        self.assertEqual(response.status_code, 404)

    def test_admin_can_open_create_page(self):
        admin_user = get_user_model().objects.create_user(username="admin", password="admin-pass", is_staff=True)
        self.client.force_login(admin_user)
        response = self.client.get(reverse("testimony_article_create"))
        self.assertEqual(response.status_code, 200)


class TestimonyArticleListTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="m1", password="pass")
        self.other_user = User.objects.create_user(username="m2", password="pass")
        self.department = Department.objects.create(code="UN", name="UN")
        self.other_department = Department.objects.create(code="WV", name="WV")
        self.member = Member.objects.create(name="Member1", user=self.user, is_active=True)
        self.other_member = Member.objects.create(name="Member2", user=self.other_user, is_active=True)
        MemberDepartment.objects.create(member=self.member, department=self.department)
        MemberDepartment.objects.create(member=self.other_member, department=self.other_department)
        self.product = Product.objects.create(name="UN商材")
        self.other_product = Product.objects.create(name="WV商材")
        now = timezone.now()
        self.article = Article.objects.create(
            title="Alpha testimony",
            body="Body",
            author="佐藤",
            product=self.product,
            created_by=self.user,
            testimonied_at=now.date(),
            view_count=3,
            created_at=now,
            updated_at=now,
        )
        self.other_article = Article.objects.create(
            title="Beta story",
            body="Other body",
            author="田中",
            product=self.other_product,
            created_by=self.other_user,
            testimonied_at=now.date() - timedelta(days=1),
            view_count=9,
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(days=1),
        )
        ArticleFavorite.objects.create(user=self.user, article=self.article)
        ArticleLike.objects.create(user=self.user, article=self.other_article)

    def test_article_list_filters_by_product_and_keyword(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("testimony_article_list"),
            {"product": self.product.id, "q": "佐藤"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alpha testimony")
        self.assertNotContains(response, "Beta story")
        self.assertContains(response, "すべての商材")
        self.assertContains(response, "お気に入りが多い順")
        self.assertNotContains(response, "適用")

    def test_article_list_ajax_returns_results_html(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("testimony_article_list"),
            {"sort": "views"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("data-testimony-results", payload["html"])
        self.assertLess(payload["html"].find("Beta story"), payload["html"].find("Alpha testimony"))

    def test_favorite_page_uses_article_list_ui_and_filters(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("testimony_mypage_favorites"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "お気に入り記事")
        self.assertContains(response, "Alpha testimony")
        self.assertNotContains(response, "Beta story")
        self.assertContains(response, "data-testimony-filter-form", html=False)
        self.assertContains(response, "data-testimony-results", html=False)

    def test_performance_member_dashboard_links_to_testimony(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("performance_member_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("testimony_article_list"))
        self.assertContains(response, "証を見る")

    def test_article_without_product_renders_and_is_not_product_filtered(self):
        orphan_article = Article.objects.create(
            title="No product",
            body="Body",
            author="商材なし",
            created_by=self.user,
            created_at=timezone.now(),
            updated_at=timezone.now(),
        )
        self.client.force_login(self.user)

        list_response = self.client.get(reverse("testimony_article_list"))
        self.assertEqual(list_response.status_code, 200)
        self.assertContains(list_response, "No product")

        filtered_response = self.client.get(reverse("testimony_article_list"), {"product": self.product.id})
        self.assertEqual(filtered_response.status_code, 200)
        self.assertNotContains(filtered_response, "No product")

        detail_response = self.client.get(reverse("testimony_article_detail", args=[orphan_article.id]))
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "No product")

    def test_article_form_uses_japanese_labels_and_optional_product(self):
        admin_user = get_user_model().objects.create_user(username="admin", password="admin-pass", is_staff=True)
        self.client.force_login(admin_user)
        response = self.client.get(reverse("testimony_article_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "タイトル")
        self.assertContains(response, "商材")
        self.assertContains(response, "証者・投稿者名")
        self.assertContains(response, "証日")
        self.assertNotContains(response, ">Title<", html=False)

    def test_product_management_is_admin_only(self):
        self.client.force_login(self.user)
        user_response = self.client.get(reverse("testimony_product_list"))
        self.assertEqual(user_response.status_code, 404)

        admin_user = get_user_model().objects.create_user(username="admin", password="admin-pass", is_staff=True)
        self.client.force_login(admin_user)
        admin_response = self.client.get(reverse("testimony_product_list"))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, "商材管理")
        self.assertContains(admin_response, "商材を追加")

    def test_admin_can_create_update_and_delete_product(self):
        admin_user = get_user_model().objects.create_user(username="admin", password="admin-pass", is_staff=True)
        self.client.force_login(admin_user)

        create_response = self.client.post(
            reverse("testimony_product_create"),
            {"name": "新商材", "description": "説明"},
        )
        self.assertEqual(create_response.status_code, 302)
        product = Product.objects.get(name="新商材")
        self.assertEqual(product.description, "説明")

        update_response = self.client.post(
            reverse("testimony_product_edit", args=[product.id]),
            {"name": "更新商材", "description": "更新説明"},
        )
        self.assertEqual(update_response.status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.name, "更新商材")

        delete_response = self.client.post(reverse("testimony_product_delete", args=[product.id]))
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(Product.objects.filter(id=product.id).exists())
