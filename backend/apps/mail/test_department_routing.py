from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Department
from apps.dairymetrics.services.entry_v2 import get_default_mail_group

from .forms import MailDepartmentRoutingForm
from .models import MailDepartmentRouting, MailRecipientGroup


class AddedDepartmentRoutingTests(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user("routing-admin", is_staff=True))
        self.un = Department.objects.create(code="UN", name="UN")
        self.wv = Department.objects.create(code="WV", name="WV")
        self.un_group = MailRecipientGroup.objects.create(name="既存UNグループ")
        self.wv_group = MailRecipientGroup.objects.create(name="既存WVグループ")
        MailDepartmentRouting.objects.create(department=self.un, recipient_group=self.un_group)
        MailDepartmentRouting.objects.create(department=self.wv, recipient_group=self.wv_group)

    def add_department(self, code="UNW", name="UN関西"):
        response = self.client.post(reverse("department_settings"), {
            "action": "save_department", "code": code, "name": name,
        })
        self.assertEqual(response.status_code, 200)
        return Department.objects.get(code=code)

    def routing_data(self, department, group):
        return {
            "action": "save_routing", "un_group": self.un_group.pk,
            "wv_group": self.wv_group.pk,
            MailDepartmentRoutingForm.field_name(department): group,
        }

    def test_ui_added_department_gets_setting_even_when_dashboard_display_is_off(self):
        self.client.get(reverse("mail_group_settings"))
        department = self.add_department()
        response = self.client.get(reverse("mail_group_settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "UN関西 (UNW) 決済報告")
        self.assertContains(response, f'name="department_{department.pk}_group"')
        self.assertContains(response, 'name="un_group"')
        self.assertContains(response, 'name="wv_group"')

    def test_custom_code_can_save_reload_and_supply_transaction_mail_default(self):
        department = self.add_department("NEW_TEAM", "追加部署")
        group = MailRecipientGroup.objects.create(name="追加部署の決済宛先")
        response = self.client.post(reverse("mail_group_settings"), self.routing_data(department, group.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(MailDepartmentRouting.objects.get(department=department).recipient_group, group)
        self.assertEqual(get_default_mail_group(department=department), group)
        response = self.client.get(reverse("mail_group_settings"))
        field = response.context["routing_form"][MailDepartmentRoutingForm.field_name(department)]
        self.assertEqual(str(field.value()), str(group.pk))
        self.assertEqual(get_default_mail_group(department=self.un), self.un_group)
        self.assertEqual(get_default_mail_group(department=self.wv), self.wv_group)

    def test_existing_added_department_routing_can_be_changed_and_unset(self):
        department = self.add_department()
        old_group = MailRecipientGroup.objects.create(name="以前の関西宛先")
        new_group = MailRecipientGroup.objects.create(name="新しい関西宛先")
        MailDepartmentRouting.objects.create(department=department, recipient_group=old_group)
        for group in [new_group, None]:
            response = self.client.post(reverse("mail_group_settings"), self.routing_data(
                department, group.pk if group else "",
            ))
            self.assertEqual(response.status_code, 200)
            routing = MailDepartmentRouting.objects.filter(department=department).first()
            self.assertEqual(routing.recipient_group if routing else None, group)
            if group:
                self.assertEqual(get_default_mail_group(department=department), group)
        self.assertFalse(MailDepartmentRouting.objects.filter(department=department).exists())
        self.assertEqual(get_default_mail_group(department=self.un), self.un_group)

    def test_inactive_group_is_rejected_without_changing_any_routing(self):
        department = self.add_department()
        disabled = MailRecipientGroup.objects.create(name="停止した宛先", is_active=False)
        data = self.routing_data(department, disabled.pk)
        data["un_group"] = ""
        response = self.client.post(reverse("mail_group_settings"), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn(MailDepartmentRoutingForm.field_name(department), response.context["routing_form"].errors)
        self.assertFalse(MailDepartmentRouting.objects.filter(department=department).exists())
        self.assertEqual(get_default_mail_group(department=self.un), self.un_group)

    def test_inactive_department_is_not_editable_and_its_routing_is_preserved(self):
        department = Department.objects.create(code="DISABLED", name="無効部署", is_active=False)
        MailDepartmentRouting.objects.create(department=department, recipient_group=self.un_group)
        response = self.client.get(reverse("mail_group_settings"))
        self.assertNotIn(MailDepartmentRoutingForm.field_name(department), response.context["routing_form"].fields)
        self.client.post(reverse("mail_group_settings"), {
            "action": "save_routing", "un_group": self.un_group.pk, "wv_group": self.wv_group.pk,
        })
        self.assertTrue(MailDepartmentRouting.objects.filter(department=department).exists())

    def test_non_admin_cannot_change_routing(self):
        department = self.add_department()
        self.client.force_login(get_user_model().objects.create_user("routing-member"))
        response = self.client.post(reverse("mail_group_settings"), self.routing_data(department, self.un_group.pk))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MailDepartmentRouting.objects.filter(department=department).exists())
