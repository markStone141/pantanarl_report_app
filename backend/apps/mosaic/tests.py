from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Department, Member, MemberDepartment

from .models import MosaicInteraction, MosaicInteractionTrialModel, MosaicResultType, MosaicTrialModel, MosaicVisitPurpose


class MosaicAppTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="store", password="pass123")
        self.admin = user_model.objects.create_user(username="admin", password="pass123", is_staff=True)
        self.department = Department.objects.create(code="MOSAIC", name="モザイクモール港北")
        self.member = Member.objects.create(name="接客者A", user=self.user, default_department=self.department)
        self.other_member = Member.objects.create(name="接客者B", default_department=self.department)
        MemberDepartment.objects.create(member=self.member, department=self.department)
        MemberDepartment.objects.create(member=self.other_member, department=self.department)
        self.purpose = MosaicVisitPurpose.objects.create(name="寝具相談")
        self.trial_model = MosaicTrialModel.objects.create(name="モデルA")
        self.result = MosaicResultType.objects.create(name="決済", is_success=True)

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("mosaic_dashboard"))

        self.assertRedirects(response, f"{reverse('mosaic_login')}?next={reverse('mosaic_dashboard')}")

    def test_member_can_login_with_fixed_password(self):
        response = self.client.post(
            reverse("mosaic_login"),
            {"login_id": self.user.username, "password": "1007"},
        )

        self.assertRedirects(response, reverse("mosaic_dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.id)

    def test_login_rejects_wrong_password(self):
        response = self.client.post(
            reverse("mosaic_login"),
            {"login_id": self.user.username, "password": "wrong"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "パスワードが正しくありません。")

    def test_login_rejects_user_without_member_profile(self):
        user_model = get_user_model()
        user_model.objects.create_user(username="no-member", password="x")

        response = self.client.post(
            reverse("mosaic_login"),
            {"login_id": "no-member", "password": "1007"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "このログインIDのメンバーが見つかりません。")

    def test_interaction_create_saves_log_and_defaults_credit_member(self):
        today = timezone.localdate()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("mosaic_interaction_create"),
            {
                "interaction_date": today.strftime("%Y-%m-%d"),
                "service_member": self.other_member.id,
                "age_band": "40代",
                "party_type": MosaicInteraction.PARTY_SINGLE,
                "awareness_status": MosaicInteraction.AWARENESS_KNOWN,
                "stay_duration_minutes": 25,
                "trial_models": [str(self.trial_model.id)],
                "needs": "腰が気になる",
                "talk_summary": "寝心地を確認",
                "result": self.result.id,
                "payment_amount": 120000,
                "is_return_support": "",
                "memo": "次回も提案できる",
            },
        )

        self.assertRedirects(response, reverse("mosaic_dashboard"))
        interaction = MosaicInteraction.objects.get()
        self.assertEqual(interaction.created_by, self.user)
        self.assertEqual(interaction.input_member, self.other_member)
        self.assertEqual(interaction.credited_member, self.other_member)
        self.assertEqual(interaction.payment_amount, 120000)
        self.assertEqual(interaction.awareness_status, MosaicInteraction.AWARENESS_KNOWN)
        self.assertEqual(interaction.trial_model, self.trial_model)
        self.assertEqual(MosaicInteractionTrialModel.objects.get(interaction=interaction).trial_model, self.trial_model)

    def test_interaction_create_marks_success_result_ids_for_amount_toggle(self):
        self.client.force_login(self.user)
        failed_result = MosaicResultType.objects.create(name="検討", is_success=False)

        response = self.client.get(reverse("mosaic_interaction_create"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.result.id, response.context["success_result_ids"])
        self.assertNotIn(failed_result.id, response.context["success_result_ids"])
        self.assertContains(response, "data-mosaic-amount-field")

    def test_interaction_form_hides_credit_member_for_new_interaction(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("mosaic_interaction_create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-mosaic-credit-field hidden', html=False)
        self.assertContains(response, "認知あり")
        self.assertContains(response, "認知なし")
        self.assertContains(response, "不明")

    def test_return_support_can_credit_different_member(self):
        today = timezone.localdate()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("mosaic_interaction_create"),
            {
                "interaction_date": today.strftime("%Y-%m-%d"),
                "service_member": self.member.id,
                "credited_member": self.other_member.id,
                "age_band": "50代",
                "party_type": MosaicInteraction.PARTY_PAIR,
                "awareness_status": MosaicInteraction.AWARENESS_UNCONFIRMED,
                "result": self.result.id,
                "payment_amount": 80000,
                "is_return_support": "on",
            },
        )

        self.assertRedirects(response, reverse("mosaic_dashboard"))
        interaction = MosaicInteraction.objects.get()
        self.assertTrue(interaction.is_return_support)
        self.assertEqual(interaction.service_member, self.member)
        self.assertEqual(interaction.input_member, self.member)
        self.assertEqual(interaction.credited_member, self.other_member)
        self.assertEqual(interaction.awareness_status, MosaicInteraction.AWARENESS_UNCONFIRMED)

    def test_dashboard_aggregates_today_interactions(self):
        today = timezone.localdate()
        self.client.force_login(self.user)
        MosaicInteraction.objects.create(
            interaction_date=today,
            input_member=self.member,
            service_member=self.member,
            credited_member=self.member,
            result=self.result,
            payment_amount=120000,
            created_by=self.user,
        )
        MosaicInteraction.objects.create(
            interaction_date=today,
            input_member=self.member,
            service_member=self.other_member,
            credited_member=self.other_member,
            payment_amount=0,
            created_by=self.user,
        )

        response = self.client.get(reverse("mosaic_dashboard"), {"date": today.strftime("%Y-%m-%d")})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["payload"]["total_count"], 2)
        self.assertEqual(response.context["payload"]["payment_count"], 1)
        self.assertEqual(response.context["payload"]["total_amount"], 120000)
        self.assertEqual(response.context["payload"]["close_rate"], 50.0)
        self.assertContains(response, "120,000円")

    def test_master_management_requires_staff(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("mosaic_master_index"))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("mosaic_master_index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "お試しモデル")
        self.assertNotContains(response, "来店目的")

    def test_staff_can_create_master(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("mosaic_master_create", args=["result-type"]),
            {"name": "検討", "is_success": "", "sort_order": 10, "is_active": "on"},
        )

        self.assertRedirects(response, reverse("mosaic_master_index"))
        self.assertTrue(MosaicResultType.objects.filter(name="検討").exists())
