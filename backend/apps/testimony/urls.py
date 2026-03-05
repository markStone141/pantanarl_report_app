from django.urls import path

from .views import (
    ArticleCreateView,
    ArticleDeleteView,
    ArticleDetailView,
    ArticleListView,
    ArticleUpdateView,
    MyFavoriteListView,
    MyHistoryListView,
    ToggleFavoriteView,
    ToggleLikeView,
)

urlpatterns = [
    path("", ArticleListView.as_view(), name="testimony_article_list"),
    path("articles/new/", ArticleCreateView.as_view(), name="testimony_article_create"),
    path("articles/<int:pk>/", ArticleDetailView.as_view(), name="testimony_article_detail"),
    path("articles/<int:pk>/edit/", ArticleUpdateView.as_view(), name="testimony_article_edit"),
    path("articles/<int:pk>/delete/", ArticleDeleteView.as_view(), name="testimony_article_delete"),
    path("articles/<int:pk>/favorite/", ToggleFavoriteView.as_view(), name="testimony_article_favorite"),
    path("articles/<int:pk>/like/", ToggleLikeView.as_view(), name="testimony_article_like"),
    path("mypage/favorites/", MyFavoriteListView.as_view(), name="testimony_mypage_favorites"),
    path("mypage/history/", MyHistoryListView.as_view(), name="testimony_mypage_history"),
]
