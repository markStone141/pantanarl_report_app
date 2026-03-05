from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import ArticleForm
from .models import Article, ArticleFavorite, ArticleLike, ArticleViewHistory


class ArticleListView(LoginRequiredMixin, ListView):
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
        return context


class ArticleDetailView(LoginRequiredMixin, View):
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


class ArticleCreateView(LoginRequiredMixin, CreateView):
    model = Article
    form_class = ArticleForm
    template_name = "testimony/article_form.html"

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


class ArticleUpdateView(LoginRequiredMixin, OwnerOrAdminMixin, UpdateView):
    model = Article
    form_class = ArticleForm
    template_name = "testimony/article_form.html"

    def form_valid(self, form):
        form.instance.updated_at = timezone.now()
        messages.success(self.request, "記事を更新しました。")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("testimony_article_detail", kwargs={"pk": self.object.pk})


class ArticleDeleteView(LoginRequiredMixin, OwnerOrAdminMixin, DeleteView):
    model = Article
    template_name = "testimony/article_confirm_delete.html"
    success_url = reverse_lazy("testimony_article_list")


class ToggleFavoriteView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        article = get_object_or_404(Article, pk=pk)
        favorite, created = ArticleFavorite.objects.get_or_create(user=request.user, article=article)
        if not created:
            favorite.delete()
        return redirect(request.POST.get("next") or reverse_lazy("testimony_article_detail", kwargs={"pk": pk}))


class ToggleLikeView(LoginRequiredMixin, View):
    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        article = get_object_or_404(Article, pk=pk)
        like, created = ArticleLike.objects.get_or_create(user=request.user, article=article)
        if not created:
            like.delete()
        return redirect(request.POST.get("next") or reverse_lazy("testimony_article_detail", kwargs={"pk": pk}))


class MyFavoriteListView(LoginRequiredMixin, ListView):
    template_name = "testimony/mypage_favorites.html"
    context_object_name = "favorites"
    paginate_by = 20

    def get_queryset(self):
        return (
            ArticleFavorite.objects.filter(user=self.request.user)
            .select_related("article", "article__product")
            .order_by("-created_at")
        )


class MyHistoryListView(LoginRequiredMixin, ListView):
    template_name = "testimony/mypage_history.html"
    context_object_name = "histories"
    paginate_by = 20

    def get_queryset(self):
        return (
            ArticleViewHistory.objects.filter(user=self.request.user)
            .select_related("article", "article__product")
            .order_by("-last_viewed_at")
        )
