from django.urls import path

from .views import (
    talks_comment_delete,
    talks_comment_edit,
    talks_detail,
    talks_deleted_posts_manage,
    talks_index,
    talks_login,
    talks_logout,
    talks_post_delete,
    talks_post_edit,
    talks_post_favorite_toggle,
    talks_tag_manage,
)

urlpatterns = [
    path("login/", talks_login, name="talks_login"),
    path("logout/", talks_logout, name="talks_logout"),
    path("posts/<int:post_id>/edit/", talks_post_edit, name="talks_post_edit"),
    path("posts/<int:post_id>/delete/", talks_post_delete, name="talks_post_delete"),
    path("posts/<int:post_id>/favorite/", talks_post_favorite_toggle, name="talks_post_favorite_toggle"),
    path("comments/<int:comment_id>/edit/", talks_comment_edit, name="talks_comment_edit"),
    path("comments/<int:comment_id>/delete/", talks_comment_delete, name="talks_comment_delete"),
    path("tags/", talks_tag_manage, name="talks_tag_manage"),
    path("deleted/", talks_deleted_posts_manage, name="talks_deleted_posts_manage"),
    path("", talks_index, name="talks_index"),
    path("<int:thread_id>/", talks_detail, name="talks_detail"),
]
