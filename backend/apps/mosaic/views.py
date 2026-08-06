from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import get_user_model, login as auth_login, logout as auth_logout
from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from .auth import require_mosaic_login
from .forms import (
    MosaicInteractionForm,
    MosaicLoginForm,
    MosaicResultTypeForm,
    MosaicTrialModelForm,
    MosaicVisitPurposeForm,
)
from .models import MosaicInteraction, MosaicInteractionTrialModel, MosaicResultType, MosaicTrialModel, MosaicVisitPurpose
from .selectors import mosaic_dashboard_payload


User = get_user_model()


def _nav_items(user):
    items = [
        ("mosaic_dashboard", "ダッシュボード"),
        ("mosaic_interaction_create", "接客ログ入力"),
        ("mosaic_interaction_list", "接客ログ一覧"),
    ]
    if user.is_staff:
        items.append(("mosaic_master_index", "マスタ管理"))
    return items


def _selected_date(request):
    return parse_date(request.GET.get("date") or "") or timezone.localdate()


def mosaic_login(request):
    next_url = request.POST.get("next") or request.GET.get("next") or reverse("mosaic_dashboard")
    if request.user.is_authenticated:
        return redirect(next_url if next_url.startswith("/mosaic/") else reverse("mosaic_dashboard"))
    form = MosaicLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login_id = form.cleaned_data["login_id"].strip()
        user = User.objects.filter(username=login_id, is_active=True, member_profile__isnull=False).first()
        if not user:
            form.add_error("login_id", "このログインIDのメンバーが見つかりません。")
        else:
            auth_login(request, user)
            return redirect(next_url if next_url.startswith("/mosaic/") else reverse("mosaic_dashboard"))
    return render(request, "mosaic/login.html", {"form": form, "next": next_url})


def mosaic_logout(request):
    auth_logout(request)
    return redirect("mosaic_login")


@require_mosaic_login
def mosaic_dashboard(request):
    target_date = _selected_date(request)
    context = {
        "nav_items": _nav_items(request.user),
        "payload": mosaic_dashboard_payload(target_date=target_date),
    }
    return render(request, "mosaic/dashboard.html", context)


@require_mosaic_login
def mosaic_interaction_create(request):
    initial = {"interaction_date": timezone.localdate()}
    form = MosaicInteractionForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        interaction = form.save(commit=False)
        interaction.created_by = request.user
        interaction.input_member = interaction.service_member
        if not interaction.is_return_support or interaction.credited_member_id is None:
            interaction.credited_member = interaction.service_member
        selected_trial_model_ids = _selected_trial_model_ids(request)
        if selected_trial_model_ids:
            first_trial_model = MosaicTrialModel.objects.filter(pk=selected_trial_model_ids[0]).first()
            interaction.trial_model = first_trial_model
        interaction.save()
        _save_trial_model_steps(interaction=interaction, trial_model_ids=selected_trial_model_ids)
        messages.success(request, "接客ログを保存しました。")
        return redirect(reverse("mosaic_interaction_create"))
    context = {
        "nav_items": _nav_items(request.user),
        "form": form,
        "trial_models": MosaicTrialModel.objects.active(),
        "success_result_ids": list(MosaicResultType.objects.active().filter(is_success=True).values_list("id", flat=True)),
    }
    return render(request, "mosaic/interaction_form.html", context)


@require_mosaic_login
def mosaic_interaction_list(request):
    target_date = _selected_date(request)
    interactions = (
        MosaicInteraction.objects.filter(interaction_date=target_date)
        .select_related("input_member", "service_member", "credited_member", "visit_purpose", "trial_model", "result")
        .prefetch_related("trial_model_steps__trial_model")
        .order_by("-created_at", "-id")
    )
    context = {
        "nav_items": _nav_items(request.user),
        "target_date": target_date,
        "interactions": interactions,
    }
    return render(request, "mosaic/interaction_list.html", context)


@staff_member_required
def mosaic_master_index(request):
    context = {
        "nav_items": _nav_items(request.user),
        "trial_models": MosaicTrialModel.objects.all(),
        "result_types": MosaicResultType.objects.all(),
    }
    return render(request, "mosaic/master_index.html", context)


@staff_member_required
def mosaic_master_create(request, master_type):
    form_class, template_label = _master_config(master_type)
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{template_label}を保存しました。")
        return redirect("mosaic_master_index")
    context = {
        "nav_items": _nav_items(request.user),
        "form": form,
        "master_label": template_label,
    }
    return render(request, "mosaic/master_form.html", context)


@staff_member_required
def mosaic_master_edit(request, master_type, pk):
    form_class, template_label = _master_config(master_type)
    model = form_class.Meta.model
    instance = get_object_or_404(model, pk=pk)
    form = form_class(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"{template_label}を更新しました。")
        return redirect("mosaic_master_index")
    context = {
        "nav_items": _nav_items(request.user),
        "form": form,
        "master_label": template_label,
    }
    return render(request, "mosaic/master_form.html", context)


def _master_config(master_type):
    configs = {
        "trial-model": (MosaicTrialModelForm, "お試しモデル"),
        "result-type": (MosaicResultTypeForm, "結果"),
    }
    if master_type not in configs:
        raise Http404("Unknown mosaic master type")
    return configs[master_type]


def _selected_trial_model_ids(request):
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


def _save_trial_model_steps(*, interaction, trial_model_ids):
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
