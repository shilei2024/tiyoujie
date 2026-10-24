import { api } from "./client";

export interface AnalysisModel {
  id: string;
  provider: string;
  model_name: string;
  notice: string;
  notice_version: string;
  integration_verified: boolean;
  analysis_quota_units: number;
}
export interface AnalysisPayload {
  understanding: string;
  conditions: string[];
  solution_steps: string[];
  error_location: string;
  root_causes: { category: string; evidence: string; confidence: number }[];
  knowledge_points: string[];
  hints: { level: number; text: string }[];
  uncertainties: string[];
  review_items: string[];
  answer_candidate: string;
  verification_status: "unverified";
}
export interface AnalysisItem {
  id: string;
  payload: AnalysisPayload;
  text_version_number: number;
  stale: boolean;
  reported: boolean;
  created_at: string;
  task: { billing_mode: string; provider: string; model: string };
}
export interface FeedbackItem {
  id: string;
  number: number;
  kind: "report" | "correction";
  text: string;
}

export async function ensureProviderConsent(childId: string, provider: string) {
  const notice = await api<{ guardian_notice_version: string }>(
    "auth/capabilities/",
  );
  const current = await api<{
    results: {
      scope: string;
      revoked_at: string | null;
      notice_version: string;
    }[];
  }>(`children/${childId}/consents/`);
  if (
    !current.results.some(
      (item) =>
        item.scope === provider &&
        !item.revoked_at &&
        item.notice_version === notice.guardian_notice_version,
    )
  ) {
    await api(`children/${childId}/consents/`, "POST", {
      scope: provider,
      notice_version: notice.guardian_notice_version,
    });
  }
}
