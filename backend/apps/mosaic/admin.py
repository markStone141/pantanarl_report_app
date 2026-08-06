from django.contrib import admin

from .models import MosaicInteraction, MosaicInteractionTrialModel, MosaicResultType, MosaicTrialModel, MosaicVisitPurpose


@admin.register(MosaicVisitPurpose)
class MosaicVisitPurposeAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(MosaicTrialModel)
class MosaicTrialModelAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(MosaicResultType)
class MosaicResultTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "is_success", "sort_order", "is_active")
    list_filter = ("is_success", "is_active")
    search_fields = ("name",)


@admin.register(MosaicInteraction)
class MosaicInteractionAdmin(admin.ModelAdmin):
    list_display = (
        "interaction_date",
        "service_member",
        "credited_member",
        "result",
        "payment_amount",
        "is_return_support",
    )
    list_filter = ("interaction_date", "result", "is_return_support")
    search_fields = (
        "input_member__name",
        "service_member__name",
        "credited_member__name",
        "needs",
        "talk_summary",
        "memo",
    )
    raw_id_fields = ("input_member", "service_member", "credited_member", "created_by")


@admin.register(MosaicInteractionTrialModel)
class MosaicInteractionTrialModelAdmin(admin.ModelAdmin):
    list_display = ("interaction", "step_order", "trial_model")
    list_filter = ("trial_model",)
    raw_id_fields = ("interaction",)
