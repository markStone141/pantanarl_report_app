from __future__ import annotations

from django.http import HttpRequest

from .models import MosaicInteractionTrialModel, MosaicTrialModel


def selected_trial_model_ids(request: HttpRequest) -> list[int]:
    ids = []
    seen = set()
    for raw_value in request.POST.getlist("trial_models"):
        if not raw_value.isdigit():
            continue
        value = int(raw_value)
        if value in seen:
            continue
        seen.add(value)
        ids.append(value)
    if not ids:
        raw_single = (request.POST.get("trial_model") or "").strip()
        if raw_single.isdigit():
            ids.append(int(raw_single))
    return ids


def prepare_interaction_for_save(*, interaction, user, trial_model_ids: list[int]):
    interaction.created_by = user
    interaction.input_member = interaction.service_member
    if not interaction.is_return_support or interaction.credited_member_id is None:
        interaction.credited_member = interaction.service_member
    if trial_model_ids:
        interaction.trial_model = MosaicTrialModel.objects.filter(pk=trial_model_ids[0]).first()
    return interaction


def save_trial_model_steps(*, interaction, trial_model_ids: list[int]) -> None:
    if not trial_model_ids:
        return
    valid_ids = list(MosaicTrialModel.objects.active().filter(id__in=trial_model_ids).values_list("id", flat=True))
    valid_id_set = set(valid_ids)
    steps = [
        MosaicInteractionTrialModel(
            interaction=interaction,
            trial_model_id=trial_model_id,
            step_order=index,
        )
        for index, trial_model_id in enumerate(trial_model_ids, start=1)
        if trial_model_id in valid_id_set
    ]
    if steps:
        MosaicInteractionTrialModel.objects.bulk_create(steps)
