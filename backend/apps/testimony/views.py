import os
import tempfile
from io import StringIO

from django.contrib import messages
from django.core.management import call_command
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import ArticleForm, TestimonyLoginForm
from .models import Article, ArticleFavorite, ArticleLike, ArticleViewHistory

ADMIN_USERNAME = os.getenv("ADMIN_LOGIN_USERNAME", "admin")


def _is_testimony_admin(user) -> bool:
    return bool(
        user.is_authenticated
        and (user.is_staff or user.is_superuser or user.username == ADMIN_USERNAME)
    )


def testimony_login(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("testimony_article_list")

    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if request.method == "POST":
        form = TestimonyLoginForm(request.POST)
        if form.is_valid():
            auth_login(request, form.user)
            if next_url.startswith("/"):
                return redirect(next_url)
            return redirect("testimony_article_list")
    else:
        form = TestimonyLoginForm()

    return render(request, "testimony/login.html", {"form": form, "next": next_url})


def testimony_logout(request: HttpRequest) -> HttpResponse:
    auth_logout(request)
    return redirect("testimony_login")


def testimony_admin_import(request: HttpRequest) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect(f"{reverse_lazy('testimony_login')}?next={request.path}")

    if not _is_testimony_admin(request.user):
        messages.error(request, "Admin only page.")
        return redirect("testimony_article_list")

    if request.method == "POST":
        products_csv = request.FILES.get("products_csv")
        articles_csv = request.FILES.get("articles_csv")
        source = (request.POST.get("source") or "legacy_testimony").strip() or "legacy_testimony"
        if not products_csv or not articles_csv:
            messages.error(request, "Please upload both products.csv and articles.csv.")
            return redirect("testimony_admin_import")

        temp_paths: list[str] = []
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as products_tmp:
                for chunk in products_csv.chunks():
                    products_tmp.write(chunk)
                temp_paths.append(products_tmp.name)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as articles_tmp:
                for chunk in articles_csv.chunks():
                    articles_tmp.write(chunk)
                temp_paths.append(articles_tmp.name)

            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as errors_tmp:
                temp_paths.append(errors_tmp.name)

            output = StringIO()
            call_command(
                "import_articles_csv",
                products=temp_paths[0],
                articles=temp_paths[1],
                errors=temp_paths[2],
                source=source,
                stdout=output,
                stderr=output,
            )
            log_text = output.getvalue().strip()
            if log_text:
                messages.info(request, log_text)
            else:
                messages.success(request, "CSV import completed.")
            return redirect("testimony_admin_import")
        except Exception as exc:
            messages.error(request, f"CSV import failed: {exc}")
            return redirect("testimony_admin_import")
        finally:
            for path in temp_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass

    return render(request, "testimony/admin_import.html")


class TestimonyLoginRequiredMixin(LoginRequiredMixin):
    login_url = reverse_lazy("testimony_login")


class ArticleListView(TestimonyLoginRequiredMixin, ListView):
    model = Article
    template_name = "testimony/article_list.html"
    context_object_name = "articles"
    paginate_by = 20

    def get_queryset(self):
        sort = self.request.GET.get("sort", "latest")
        keyword = (self.request.GET.get("q") or "").strip()
        qs = (
            Article.objects.select_related("product", "created_by")
            .annotate(favorite_count=Count("favorites", distinct=True), like_count=Count("likes", distinct=True))
        )
        if keyword:
            qs = qs.filter(Q(title__icontains=keyword) | Q(body__icontains=keyword) | Q(author__icontains=keyword))
        if sort == "views":
            return qs.order_by("-view_count", "-updated_at")
        if sort == "favorites":
            return qs.order_by("-favorite_count", "-updated_at")
        if sort == "likes":
            return qs.order_by("-like_count", "-updated_at")
        if sort == "popular":
            qs = qs.annotate(popularity_score=F("view_count") + (3 * F("favorite_count")) + (2 * F("like_count")))
            return qs.order_by("-popularity_score", "-updated_at")
        return qs.order_by("-updated_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["selected_sort"] = self.request.GET.get("sort", "latest")
        context["q"] = (self.request.GET.get("q") or "").strip()
        context["can_create_article"] = _is_testimony_admin(self.request.user)
        params = self.request.GET.copy()
        params.pop("page", None)
        context["pagination_query"] = params.urlencode()
        return context


class ArticleDetailView(TestimonyLoginRequiredMixin, View):
    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        article = get_object_or_404(
            Article.objects.select_related("product", "created_by").annotate(
                favorite_count=Count("favorites", distinct=True),
                like_count=Count("likes", distinct=True),
            ),
            pk=pk,
        )

        with transaction.atomic():
            now = timezone.now()
            history, created = ArticleViewHistory.objects.select_for_update().get_or_create(
                user=request.user,
                article=article,
                defaults={
                    "first_viewed_at": now,
                    "last_viewed_at": now,
                    "view_count": 1,
                },
            )
            if not created:
                history.last_viewed_at = now
                history.view_count = F("view_count") + 1
                history.save(update_fields=["last_viewed_at", "view_count"])
            Article.objects.filter(pk=article.pk).update(view_count=F("view_count") + 1)

        article.refresh_from_db()

        return render(
            request,
            "testimony/article_detail.html",
            {
                "article": article,
                "is_favorited": ArticleFavorite.objects.filter(user=request.user, article=article).exists(),
                "is_liked": ArticleLike.objects.filter(user=request.user, article=article).exists(),
            },
        )


class ArticleCreateView(TestimonyLoginRequiredMixin, CreateView):
    model = Article
    form_class = ArticleForm
    template_name = "testimony/article_form.html"

    def dispatch(self, request: HttpRequest, *args, **kwargs):
        if not _is_testimony_admin(request.user):
            raise Http404()
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        now = timezone.now()
        form.instance.created_by = self.request.user
        form.instance.created_at = now
        form.instance.updated_at = now
        messages.success(self.request, "記事を作成しました。")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("testimony_article_detail", kwargs={"pk": self.object.pk})


class OwnerOrAdminMixin(UserPassesTestMixin):
    def test_func(self):
        article = self.get_object()
        user = self.request.user
        return bool(user.is_staff or user.is_superuser or article.created_by_id == user.id)

    def handle_no_permission(self):
        raise Http404()


class ArticleUpdateView(TestimonyLoginRequiredMixin, OwnerOrAdminMixin, UpdateView):
    model = Article
    form_class = ArticleForm
    template_name = "testimony/article_form.html"

    def form_valid(self, form):
        form.instance.updated_at = timezone.now()
        messages.success(self.request, "記事を更新しました。")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("testimony_article_detail", kwargs={"pk": self.object.pk})


class ArticleDeleteView(TestimonyLoginRequiredMixin, OwnerOrAdminMixin, DeleteView):
    model = Article
    template_name = "testimony/article_confirm_delete.html"
    success_url = reverse_lazy("testimony_article_list")


class ToggleFavoriteView(TestimonyLoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        article = get_object_or_404(Article, pk=pk)
        favorite, created = ArticleFavorite.objects.get_or_create(user=request.user, article=article)
        if not created:
            favorite.delete()
        is_favorited = created
        favorite_count = ArticleFavorite.objects.filter(article=article).count()
        like_count = ArticleLike.objects.filter(article=article).count()

        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        if is_ajax:
            return JsonResponse(
                {
                    "ok": True,
                    "is_favorited": is_favorited,
                    "is_liked": ArticleLike.objects.filter(user=request.user, article=article).exists(),
                    "favorite_count": favorite_count,
                    "like_count": like_count,
                }
            )
        return redirect(request.POST.get("next") or reverse_lazy("testimony_article_detail", kwargs={"pk": pk}))


class ToggleLikeView(TestimonyLoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        article = get_object_or_404(Article, pk=pk)
        like, created = ArticleLike.objects.get_or_create(user=request.user, article=article)
        if not created:
            like.delete()
        is_liked = created
        favorite_count = ArticleFavorite.objects.filter(article=article).count()
        like_count = ArticleLike.objects.filter(article=article).count()

        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
        if is_ajax:
            return JsonResponse(
                {
                    "ok": True,
                    "is_favorited": ArticleFavorite.objects.filter(user=request.user, article=article).exists(),
                    "is_liked": is_liked,
                    "favorite_count": favorite_count,
                    "like_count": like_count,
                }
            )
        return redirect(request.POST.get("next") or reverse_lazy("testimony_article_detail", kwargs={"pk": pk}))


class MyFavoriteListView(TestimonyLoginRequiredMixin, ListView):
    template_name = "testimony/mypage_favorites.html"
    context_object_name = "favorites"
    paginate_by = 20

    def get_queryset(self):
        return (
            ArticleFavorite.objects.filter(user=self.request.user)
            .select_related("article", "article__product")
            .order_by("-created_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        context["pagination_query"] = params.urlencode()
        return context


class MyHistoryListView(TestimonyLoginRequiredMixin, ListView):
    template_name = "testimony/mypage_history.html"
    context_object_name = "histories"
    paginate_by = 20

    def get_queryset(self):
        return (
            ArticleViewHistory.objects.filter(user=self.request.user)
            .select_related("article", "article__product")
            .order_by("-last_viewed_at")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        context["pagination_query"] = params.urlencode()
        return context
