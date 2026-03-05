from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.auth import ROLE_ADMIN, ROLE_REPORT, SESSION_ROLE_KEY
from apps.accounts.models import Member
from apps.talks.models import (
    KnowledgeComment,
    KnowledgePost,
    KnowledgePostFavorite,
    KnowledgePostRead,
    KnowledgePostTag,
    KnowledgeReactionType,
    KnowledgeTag,
    KnowledgeUserPreference,
)
from apps.talks.views import TALKS_SESSION_IS_ADMIN_KEY, TALKS_SESSION_MEMBER_ID_KEY


class TalksBaseTestCase(TestCase):
    def setUp(self):
        self.good = KnowledgeReactionType.objects.create(
            code="good",
            label="Good",
            icon_class="fa-solid fa-thumbs-up",
            color="#1e7c4d",
            sort_order=0,
            is_active=True,
        )
        self.keep = KnowledgeReactionType.objects.create(
            code="keep",
            label="Keep",
            icon_class="fa-solid fa-hand",
            color="#355767",
            sort_order=1,
            is_active=True,
        )
        self.retry = KnowledgeReactionType.objects.create(
            code="retry",
            label="Retry",
            icon_class="fa-solid fa-rotate-right",
            color="#9b3838",
            sort_order=2,
            is_active=True,
        )
        self.question = KnowledgeReactionType.objects.create(
            code="question",
            label="Question",
            icon_class="fa-solid fa-circle-question",
            color="#7454a6",
            sort_order=3,
            is_active=True,
        )

        self.tag_un = KnowledgeTag.objects.create(name="UN", sort_order=1, is_active=True)
        self.tag_wv = KnowledgeTag.objects.create(name="WV", sort_order=2, is_active=True)
        self.tag_retry = KnowledgeTag.objects.create(name="切り返し", sort_order=3, is_active=True)

        self.member1 = Member.objects.create(
            name="Alice",
            login_id="alice",
            password="pass1",
            is_active=True,
        )
        self.member2 = Member.objects.create(
            name="Bob",
            login_id="bob",
            password="pass2",
            is_active=True,
        )
        user_model = get_user_model()
        self.member1.user = user_model.objects.create_user(username="alice", password="pass1")
        self.member1.save(update_fields=["user"])
        self.member2.user = user_model.objects.create_user(username="bob", password="pass2")
        self.member2.save(update_fields=["user"])

        self.post1 = self._create_post(self.member1, "Post1", "Body1", [self.tag_un, self.tag_retry])
        self.post2 = self._create_post(self.member2, "Post2", "Body2", [self.tag_un])
        self.post3 = self._create_post(self.member2, "Post3", "Body3", [self.tag_wv])

    def _create_post(self, author, title, body, tags):
        post = KnowledgePost.objects.create(
            title=title,
            body=body,
            author_member=author,
            author_name_snapshot=author.name,
            status=KnowledgePost.Status.PUBLISHED,
            is_deleted=False,
            published_at=timezone.now(),
        )
        for tag in tags:
            KnowledgePostTag.objects.create(post=post, tag=tag)
        return post

    def _login_talks_member(self, login_id, password):
        return self.client.post(reverse("talks_login"), {"login_id": login_id, "password": password})

    def _set_role_admin_session(self):
        session = self.client.session
        session[SESSION_ROLE_KEY] = ROLE_ADMIN
        session[TALKS_SESSION_IS_ADMIN_KEY] = True
        session[TALKS_SESSION_MEMBER_ID_KEY] = None
        session.save()


class TalksModelTests(TalksBaseTestCase):
    def test_knowledge_post_tag_unique_constraint(self):
        with self.assertRaises(IntegrityError):
            KnowledgePostTag.objects.create(post=self.post1, tag=self.tag_un)

    def test_comment_cannot_be_nested_over_one_level(self):
        top = KnowledgeComment.objects.create(
            post=self.post1,
            author_member=self.member1,
            author_name_snapshot=self.member1.name,
            body="top",
            reaction_type=self.good,
            is_deleted=False,
        )
        reply = KnowledgeComment.objects.create(
            post=self.post1,
            author_member=self.member2,
            author_name_snapshot=self.member2.name,
            body="reply",
            reaction_type=self.good,
            parent=top,
            is_deleted=False,
        )
        nested = KnowledgeComment(
            post=self.post1,
            author_member=self.member1,
            author_name_snapshot=self.member1.name,
            body="nested",
            reaction_type=self.good,
            parent=reply,
            is_deleted=False,
        )
        with self.assertRaises(ValidationError):
            nested.full_clean()

    def test_post_read_unique_for_user_and_post(self):
        user = get_user_model().objects.create_user(username="u1")
        KnowledgePostRead.objects.create(user=user, post=self.post1)
        with self.assertRaises(IntegrityError):
            KnowledgePostRead.objects.create(user=user, post=self.post1)

    def test_post_favorite_unique_for_user_and_post(self):
        user = get_user_model().objects.create_user(username="u2")
        KnowledgePostFavorite.objects.create(user=user, post=self.post1)
        with self.assertRaises(IntegrityError):
            KnowledgePostFavorite.objects.create(user=user, post=self.post1)


class TalksAuthTests(TalksBaseTestCase):
    def test_member_login_sets_report_role_and_redirects(self):
        response = self._login_talks_member("alice", "pass1")
        self.assertRedirects(response, reverse("talks_index"))
        self.assertEqual(self.client.session.get(SESSION_ROLE_KEY), ROLE_REPORT)

    def test_admin_login_sets_admin_role_and_redirects(self):
        response = self.client.post(reverse("talks_login"), {"login_id": "admin", "password": "pnadmin"})
        self.assertRedirects(response, reverse("talks_index"))
        self.assertEqual(self.client.session.get(SESSION_ROLE_KEY), ROLE_ADMIN)

    def test_talks_index_requires_authentication(self):
        response = self.client.get(reverse("talks_index"))
        self.assertRedirects(response, reverse("talks_login"))

    def test_member_without_linked_user_cannot_login(self):
        member = Member.objects.create(
            name="NoUser",
            login_id="nouser",
            password="dummy",
            is_active=True,
        )
        self.assertIsNone(member.user)
        response = self.client.post(reverse("talks_login"), {"login_id": "nouser", "password": "dummy"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "IDまたはパスワードが違います。")


class TalksCrudTests(TalksBaseTestCase):
    def test_create_post(self):
        self._login_talks_member("alice", "pass1")
        response = self.client.post(
            reverse("talks_index"),
            {
                "action": "create_post",
                "title": "New Post",
                "body": "New Body",
                "tags": ["UN", "切り返し"],
            },
        )
        self.assertEqual(response.status_code, 302)
        created = KnowledgePost.objects.get(title="New Post")
        self.assertEqual(created.author_member_id, self.member1.id)
        self.assertEqual(created.tags.count(), 2)

    def test_edit_own_post(self):
        self._login_talks_member("alice", "pass1")
        response = self.client.post(
            reverse("talks_post_edit", args=[self.post1.id]),
            {"title": "Post1-Edited", "body": "Body1-Edited", "tags": ["UN"]},
        )
        self.assertRedirects(response, reverse("talks_detail", args=[self.post1.id]))
        self.post1.refresh_from_db()
        self.assertEqual(self.post1.title, "Post1-Edited")
        self.assertEqual(list(self.post1.tags.values_list("name", flat=True)), ["UN"])

    def test_delete_own_post_soft_delete(self):
        self._login_talks_member("alice", "pass1")
        response = self.client.post(reverse("talks_post_delete", args=[self.post1.id]))
        self.assertRedirects(response, reverse("talks_index"))
        self.post1.refresh_from_db()
        self.assertTrue(self.post1.is_deleted)

    def test_other_member_cannot_edit_post(self):
        self._login_talks_member("bob", "pass2")
        response = self.client.get(reverse("talks_post_edit", args=[self.post1.id]))
        self.assertEqual(response.status_code, 404)

    def test_comment_crud_and_reply_inherits_reaction(self):
        self._login_talks_member("alice", "pass1")
        create_response = self.client.post(
            reverse("talks_detail", args=[self.post1.id]),
            {"body": "top-comment", "reaction_code": "good"},
        )
        self.assertRedirects(create_response, reverse("talks_detail", args=[self.post1.id]))
        top = KnowledgeComment.objects.get(body="top-comment")
        self.assertEqual(top.reaction_type.code, "good")

        reply_response = self.client.post(
            reverse("talks_detail", args=[self.post1.id]),
            {"body": "reply-comment", "parent_id": str(top.id)},
        )
        self.assertRedirects(reply_response, reverse("talks_detail", args=[self.post1.id]))
        reply = KnowledgeComment.objects.get(body="reply-comment")
        self.assertEqual(reply.parent_id, top.id)
        self.assertEqual(reply.reaction_type_id, top.reaction_type_id)

        edit_response = self.client.post(
            reverse("talks_comment_edit", args=[top.id]),
            {"body": "top-comment-edited"},
        )
        self.assertRedirects(edit_response, reverse("talks_detail", args=[self.post1.id]))
        top.refresh_from_db()
        self.assertEqual(top.body, "top-comment-edited")

        delete_response = self.client.post(reverse("talks_comment_delete", args=[top.id]))
        self.assertRedirects(delete_response, reverse("talks_detail", args=[self.post1.id]))
        top.refresh_from_db()
        self.assertTrue(top.is_deleted)

    def test_toggle_favorite(self):
        self._login_talks_member("alice", "pass1")
        toggle_on = self.client.post(
            reverse("talks_post_favorite_toggle", args=[self.post1.id]),
            {"next": reverse("talks_index")},
        )
        self.assertRedirects(toggle_on, reverse("talks_index"))
        self.assertTrue(
            KnowledgePostFavorite.objects.filter(
                user_id=self.client.session.get("_auth_user_id"),
                post=self.post1,
            ).exists()
        )

        toggle_off = self.client.post(
            reverse("talks_post_favorite_toggle", args=[self.post1.id]),
            {"next": reverse("talks_index")},
        )
        self.assertRedirects(toggle_off, reverse("talks_index"))
        self.assertFalse(
            KnowledgePostFavorite.objects.filter(
                user_id=self.client.session.get("_auth_user_id"),
                post=self.post1,
            ).exists()
        )

    def test_toggle_favorite_returns_json_for_ajax(self):
        self._login_talks_member("alice", "pass1")
        response = self.client.post(
            reverse("talks_post_favorite_toggle", args=[self.post1.id]),
            {"next": reverse("talks_index")},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["post_id"], self.post1.id)
        self.assertTrue(payload["is_favorite"])


class TalksFilteringAndUnreadTests(TalksBaseTestCase):
    def test_tag_filter_uses_and_condition(self):
        self._login_talks_member("alice", "pass1")
        response = self.client.get(reverse("talks_index"), {"tag": ["UN", "切り返し"]})
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.context["threads"]]
        self.assertEqual(ids, [self.post1.id])

    def test_unread_flag_and_unread_only_filter(self):
        self._login_talks_member("alice", "pass1")
        user = self.client.session.get("_auth_user_id")
        self.assertIsNotNone(user)
        django_user = get_user_model().objects.get(id=user)

        old_read_time = timezone.now() - timedelta(days=1)
        read = KnowledgePostRead.objects.create(user=django_user, post=self.post1)
        KnowledgePostRead.objects.filter(id=read.id).update(read_at=old_read_time)
        KnowledgePost.objects.filter(id=self.post1.id).update(updated_at=timezone.now())

        response = self.client.get(reverse("talks_index"))
        thread_map = {t["id"]: t for t in response.context["threads"]}
        self.assertTrue(thread_map[self.post1.id]["is_unread"])

        only_unread = self.client.get(reverse("talks_index"), {"unread": "1"})
        ids = [item["id"] for item in only_unread.context["threads"]]
        self.assertIn(self.post1.id, ids)

    def test_favorite_only_filter(self):
        self._login_talks_member("alice", "pass1")
        user_id = self.client.session.get("_auth_user_id")
        KnowledgePostFavorite.objects.create(user_id=user_id, post=self.post2)

        response = self.client.get(reverse("talks_index"), {"favorite": "1"})
        self.assertEqual(response.status_code, 200)
        ids = [item["id"] for item in response.context["threads"]]
        self.assertEqual(ids, [self.post2.id])

    def test_preferred_tags_are_kept_across_logout_login(self):
        self._login_talks_member("alice", "pass1")
        response = self.client.get(reverse("talks_index"), {"tag": ["WV"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.context["threads"]], [self.post3.id])

        user_id = self.client.session.get("_auth_user_id")
        pref = KnowledgeUserPreference.objects.get(user_id=user_id)
        self.assertEqual(
            list(pref.preferred_tags.order_by("name").values_list("name", flat=True)),
            ["WV"],
        )

        self.client.get(reverse("talks_logout"))
        self._login_talks_member("alice", "pass1")
        response2 = self.client.get(reverse("talks_index"))
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(response2.context["selected_tags"], ["WV"])
        self.assertEqual([item["id"] for item in response2.context["threads"]], [self.post3.id])


class TalksAdminPermissionTests(TalksBaseTestCase):
    def test_tag_manage_requires_admin(self):
        self._login_talks_member("alice", "pass1")
        response = self.client.get(reverse("talks_tag_manage"))
        self.assertRedirects(response, reverse("talks_index"))

    def test_role_admin_can_access_tag_manage_without_talks_flag(self):
        self._set_role_admin_session()
        response = self.client.get(reverse("talks_tag_manage"))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_create_and_toggle_tag(self):
        self._set_role_admin_session()
        create = self.client.post(
            reverse("talks_tag_manage"),
            {"name": "新タグ", "is_active": "on"},
        )
        self.assertRedirects(create, reverse("talks_tag_manage"))
        tag = KnowledgeTag.objects.get(name="新タグ")
        self.assertTrue(tag.is_active)

        toggle = self.client.post(
            reverse("talks_tag_manage"),
            {"action": "toggle", "tag_id": str(tag.id)},
        )
        self.assertRedirects(toggle, reverse("talks_tag_manage"))
        tag.refresh_from_db()
        self.assertFalse(tag.is_active)

    def test_admin_can_bulk_add_tags(self):
        self._set_role_admin_session()
        response = self.client.post(
            reverse("talks_tag_manage"),
            {
                "action": "bulk_add",
                "bulk_names": "新規A\n新規B,新規C\nUN",
            },
        )
        self.assertRedirects(response, reverse("talks_tag_manage"))
        self.assertTrue(KnowledgeTag.objects.filter(name="新規A").exists())
        self.assertTrue(KnowledgeTag.objects.filter(name="新規B").exists())
        self.assertTrue(KnowledgeTag.objects.filter(name="新規C").exists())
        # Existing tag should not be duplicated.
        self.assertEqual(KnowledgeTag.objects.filter(name="UN").count(), 1)

    def test_admin_can_delete_inactive_unused_tag(self):
        self._set_role_admin_session()
        tag = KnowledgeTag.objects.create(name="削除対象", is_active=False)
        response = self.client.post(
            reverse("talks_tag_manage"),
            {"action": "delete", "tag_id": str(tag.id)},
        )
        self.assertRedirects(response, reverse("talks_tag_manage"))
        self.assertFalse(KnowledgeTag.objects.filter(id=tag.id).exists())

    def test_admin_cannot_delete_inactive_used_tag(self):
        self._set_role_admin_session()
        self.tag_un.is_active = False
        self.tag_un.save(update_fields=["is_active", "updated_at"])
        response = self.client.post(
            reverse("talks_tag_manage"),
            {"action": "delete", "tag_id": str(self.tag_un.id)},
        )
        self.assertRedirects(response, reverse("talks_tag_manage"))
        self.assertTrue(KnowledgeTag.objects.filter(id=self.tag_un.id).exists())

    def test_admin_can_manage_other_users_posts(self):
        self._set_role_admin_session()
        response = self.client.post(
            reverse("talks_post_edit", args=[self.post1.id]),
            {"title": "Admin Edited", "body": "Edited", "tags": ["UN"]},
        )
        self.assertRedirects(response, reverse("talks_detail", args=[self.post1.id]))
        self.post1.refresh_from_db()
        self.assertEqual(self.post1.title, "Admin Edited")

    def test_deleted_posts_manage_requires_admin(self):
        self._login_talks_member("alice", "pass1")
        response = self.client.get(reverse("talks_deleted_posts_manage"))
        self.assertRedirects(response, reverse("talks_index"))

    def test_admin_can_restore_deleted_post(self):
        self.post1.is_deleted = True
        self.post1.save(update_fields=["is_deleted", "updated_at"])
        self._set_role_admin_session()

        response = self.client.post(
            reverse("talks_deleted_posts_manage"),
            {"action": "restore", "post_id": str(self.post1.id)},
        )
        self.assertRedirects(response, reverse("talks_deleted_posts_manage"))
        self.post1.refresh_from_db()
        self.assertFalse(self.post1.is_deleted)

    def test_admin_can_hard_delete_post(self):
        self.post1.is_deleted = True
        self.post1.save(update_fields=["is_deleted", "updated_at"])
        self._set_role_admin_session()

        response = self.client.post(
            reverse("talks_deleted_posts_manage"),
            {"action": "hard_delete", "post_id": str(self.post1.id)},
        )
        self.assertRedirects(response, reverse("talks_deleted_posts_manage"))
        self.assertFalse(KnowledgePost.objects.filter(id=self.post1.id).exists())
