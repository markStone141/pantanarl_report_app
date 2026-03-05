from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Article, ArticleFavorite, ArticleViewHistory, Product


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
