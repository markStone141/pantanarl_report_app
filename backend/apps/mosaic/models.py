from django.conf import settings
from django.db import models

from apps.accounts.models import Member


class ActiveOrderedMasterQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class MosaicMasterBase(models.Model):
    name = models.CharField(max_length=80, unique=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ActiveOrderedMasterQuerySet.as_manager()

    class Meta:
        abstract = True
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class MosaicVisitPurpose(MosaicMasterBase):
    class Meta(MosaicMasterBase.Meta):
        verbose_name = "来店目的"
        verbose_name_plural = "来店目的"


class MosaicTrialModel(MosaicMasterBase):
    class Meta(MosaicMasterBase.Meta):
        verbose_name = "お試しモデル"
        verbose_name_plural = "お試しモデル"


class MosaicResultType(MosaicMasterBase):
    is_success = models.BooleanField(default=False)

    class Meta(MosaicMasterBase.Meta):
        verbose_name = "結果"
        verbose_name_plural = "結果"


class MosaicInteraction(models.Model):
    PARTY_SINGLE = "single"
    PARTY_PAIR = "pair"
    PARTY_GROUP = "group"
    PARTY_CHOICES = [
        (PARTY_SINGLE, "1人"),
        (PARTY_PAIR, "2人"),
        (PARTY_GROUP, "それ以上"),
    ]
    AWARENESS_KNOWN = "known"
    AWARENESS_UNKNOWN = "unknown"
    AWARENESS_UNCONFIRMED = "unconfirmed"
    AWARENESS_CHOICES = [
        (AWARENESS_KNOWN, "認知あり"),
        (AWARENESS_UNKNOWN, "認知なし"),
        (AWARENESS_UNCONFIRMED, "不明"),
    ]

    interaction_date = models.DateField("日付")
    input_member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mosaic_input_interactions",
        verbose_name="入力者",
    )
    service_member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mosaic_service_interactions",
        verbose_name="接客者",
    )
    credited_member = models.ForeignKey(
        Member,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mosaic_credited_interactions",
        verbose_name="実績扱い",
    )
    age_band = models.CharField("年代", max_length=32, blank=True)
    party_type = models.CharField("人数区分", max_length=16, choices=PARTY_CHOICES, blank=True)
    visit_purpose = models.ForeignKey(
        MosaicVisitPurpose,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interactions",
        verbose_name="来店目的",
    )
    awareness_status = models.CharField("認知状況", max_length=16, choices=AWARENESS_CHOICES, blank=True)
    stay_duration_minutes = models.PositiveIntegerField("滞在時間（分）", null=True, blank=True)
    trial_model = models.ForeignKey(
        MosaicTrialModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interactions",
        verbose_name="お試しモデル",
    )
    needs = models.TextField("ニーズ", blank=True)
    talk_summary = models.TextField("トーク内容", blank=True)
    result = models.ForeignKey(
        MosaicResultType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interactions",
        verbose_name="結果",
    )
    payment_amount = models.PositiveIntegerField("決済金額", default=0)
    is_return_support = models.BooleanField("戻り対応", default=False)
    memo = models.TextField("メモ", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mosaic_created_interactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-interaction_date", "-created_at", "-id"]
        indexes = [
            models.Index(fields=["interaction_date"], name="mosaic_inter_date_idx"),
            models.Index(fields=["credited_member", "interaction_date"], name="mosaic_inter_credit_idx"),
            models.Index(fields=["service_member", "interaction_date"], name="mosaic_inter_service_idx"),
            models.Index(fields=["result", "interaction_date"], name="mosaic_inter_result_idx"),
        ]

    def __str__(self) -> str:
        member_name = self.service_member.name if self.service_member else "未選択"
        return f"{self.interaction_date} {member_name}"


class MosaicInteractionTrialModel(models.Model):
    interaction = models.ForeignKey(
        MosaicInteraction,
        on_delete=models.CASCADE,
        related_name="trial_model_steps",
    )
    trial_model = models.ForeignKey(
        MosaicTrialModel,
        on_delete=models.CASCADE,
        related_name="interaction_steps",
    )
    step_order = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["step_order", "id"]
        unique_together = ("interaction", "trial_model")

    def __str__(self) -> str:
        return f"{self.interaction_id} #{self.step_order} {self.trial_model.name}"
