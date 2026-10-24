from django.contrib import admin
from django.urls import path

from apps.accounts import views as accounts
from apps.ai_tutor import views as ai_tutor
from apps.credentials import views as credentials
from apps.entitlements import views as entitlements
from apps.infrastructure.views import LiveView, ReadyView
from apps.ocr import views as ocr
from apps.practice import views as practice
from apps.problems import views as problems
from apps.question_bank import views as bank

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/live/", LiveView.as_view()),
    path("api/v1/health/ready/", ReadyView.as_view()),
    path("api/v1/auth/capabilities/", accounts.Capabilities.as_view()),
    path("api/v1/auth/dev-login/", accounts.DevLogin.as_view()),
    path("api/v1/auth/wechat-login/", accounts.WechatLogin.as_view()),
    path("api/v1/auth/refresh/", accounts.Refresh.as_view()),
    path("api/v1/auth/logout/", accounts.Logout.as_view()),
    path("api/v1/auth/me/", accounts.Me.as_view()),
    path("api/v1/families/", accounts.Families.as_view()),
    path("api/v1/families/<uuid:pk>/", accounts.FamilyDetail.as_view()),
    path("api/v1/families/<uuid:pk>/members/", accounts.Members.as_view()),
    path("api/v1/families/<uuid:pk>/invitations/", accounts.Invitations.as_view()),
    path("api/v1/invitations/accept/", accounts.AcceptInvitation.as_view()),
    path("api/v1/family-members/<uuid:pk>/", accounts.MemberDetail.as_view()),
    path("api/v1/children/", accounts.Children.as_view()),
    path("api/v1/children/<uuid:pk>/", accounts.ChildDetail.as_view()),
    path("api/v1/children/<uuid:pk>/update/", accounts.ChildUpdate.as_view()),
    path("api/v1/children/<uuid:pk>/consents/", accounts.Consents.as_view()),
    path("api/v1/children/<uuid:pk>/consents/<uuid:consent_id>/", accounts.RevokeConsent.as_view()),
    path("api/v1/account-deletion-jobs/", accounts.AccountDeletion.as_view()),
    path("api/v1/deletion-requests/<uuid:pk>/", accounts.DeletionStatus.as_view()),
    path("api/v1/provider-credentials/", credentials.CredentialsView.as_view()),
    path("api/v1/provider-credentials/<uuid:pk>/", credentials.CredentialDetail.as_view()),
    path("api/v1/provider-credentials/<uuid:pk>/state/", credentials.CredentialState.as_view()),
    path("api/v1/provider-credentials/<uuid:pk>/replace/", credentials.CredentialReplace.as_view()),
    path("api/v1/entitlements/me/", entitlements.EntitlementsMe.as_view()),
    path("api/v1/promotion-campaigns/eligible/", entitlements.EligibleCampaigns.as_view()),
    path("api/v1/promotion-campaigns/<uuid:pk>/claim/", entitlements.ClaimCampaign.as_view()),
    path("api/v1/notifications/", entitlements.Notifications.as_view()),
    path("api/v1/problems/", problems.Problems.as_view()),
    path("api/v1/problems/<uuid:pk>/", problems.ProblemDetail.as_view()),
    path("api/v1/problems/<uuid:pk>/update/", problems.ProblemUpdate.as_view()),
    path("api/v1/problems/<uuid:pk>/text/", problems.ProblemText.as_view()),
    path("api/v1/problems/<uuid:pk>/text-versions/", problems.TextVersions.as_view()),
    path("api/v1/problems/<uuid:pk>/assets/", problems.UploadAsset.as_view()),
    path("api/v1/problems/<uuid:pk>/asset-links/", problems.AttachAsset.as_view()),
    path(
        "api/v1/problems/<uuid:pk>/assets/<uuid:asset_id>/remove/", problems.DetachAsset.as_view()
    ),
    path("api/v1/assets/<uuid:pk>/content/", problems.AssetContent.as_view()),
    path("api/v1/assets/<uuid:pk>/transforms/", problems.TransformAsset.as_view()),
    path("api/v1/ocr/models/", ocr.Models.as_view()),
    path("api/v1/ai/models/", ai_tutor.Models.as_view()),
    path("api/v1/ai/schema/", ai_tutor.Schema.as_view()),
    path("api/v1/ai/preference/", ai_tutor.Preference.as_view()),
    path("api/v1/problems/<uuid:pk>/analysis-jobs/", ai_tutor.Jobs.as_view()),
    path("api/v1/problems/<uuid:pk>/analyses/", ai_tutor.Results.as_view()),
    path("api/v1/analyses/<uuid:pk>/feedback/", ai_tutor.Feedback.as_view()),
    path("api/v1/problems/<uuid:pk>/ocr-jobs/", ocr.CreateOCR.as_view()),
    path("api/v1/tasks/<uuid:pk>/", ocr.Task.as_view()),
    path("api/v1/tasks/<uuid:pk>/cancel/", ocr.CancelTask.as_view()),
    path("api/v1/usage/summary/", ocr.UsageSummary.as_view()),
    path("api/v1/knowledge-points/", bank.Points.as_view()),
    path("api/v1/question-bank/<uuid:pk>/", bank.Item.as_view()),
    path("api/v1/problems/<uuid:pk>/similar/", bank.Similar.as_view()),
    path("api/v1/problems/<uuid:pk>/variants/", bank.Variants.as_view()),
    path("api/v1/worksheets/", practice.Worksheets.as_view()),
    path("api/v1/worksheets/<uuid:pk>/", practice.WorksheetDetail.as_view()),
    path("api/v1/worksheets/<uuid:pk>/items/", practice.WorksheetItems.as_view()),
    path(
        "api/v1/worksheets/<uuid:pk>/items/<uuid:item_id>/",
        practice.WorksheetItemDetail.as_view(),
    ),
    path(
        "api/v1/worksheets/<uuid:pk>/items/<uuid:item_id>/attempts/",
        practice.WorksheetAttempts.as_view(),
    ),
    path("api/v1/reviews/queue/", practice.ReviewQueue.as_view()),
    path("api/v1/problems/<uuid:pk>/review/", practice.GradeReview.as_view()),
    path("api/v1/children/<uuid:pk>/trends/", practice.Trends.as_view()),
    path("api/v1/exports/", practice.Exports.as_view()),
    path("api/v1/exports/<str:nonce>/", practice.ExportDownload.as_view()),
]
