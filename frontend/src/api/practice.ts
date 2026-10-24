import { api } from "./client";
import { session } from "../state";

export interface WorksheetSummary {
  id: string;
  child_id: string;
  title: string;
  revision: number;
  created_at: string;
}
export interface WorksheetItem {
  id: string;
  position: number;
  origin: "problem" | "bank" | "variant";
  text?: string;
  answer?: string;
  explanation?: string;
  knowledge_points: string[];
  source_available: boolean;
  attempts: number;
  last_grade: string | null;
  last_correct: boolean | null;
  attempts_detail?: AttemptRow[];
}
export interface AttemptRow {
  id: string;
  number: number;
  answer: string;
  self_grade: string;
  is_correct: boolean | null;
  graded_by: string;
  duration_seconds: number | null;
  created_at: string;
}
export interface WorksheetDetail {
  id: string;
  child_id: string;
  title: string;
  revision: number;
  item_count: number;
  items: WorksheetItem[];
}
export interface QueueRow {
  problem_id: string;
  text: string;
  due_on: string;
  overdue_days: number;
  stage: string;
  interval_days: number;
  streak: number;
}
export interface Queue {
  date: string;
  counts: {
    due: number;
    new: number;
    mastered: number;
    learning: number;
    review: number;
  };
  results: QueueRow[];
}
export interface Trend {
  weeks: {
    start: string;
    problems_added: number;
    attempts: number;
    correct: number;
    wrong: number;
    unsure: number;
  }[];
  review: { due: number; mastered: number; learning: number; review: number };
  knowledge_points: {
    code: string;
    attempts: number;
    correct: number;
    accuracy: number | null;
    insufficient_sample: boolean;
  }[];
  sample: {
    attempts: number;
    min_required: number;
    sufficient: boolean;
    note: string;
  };
}

export function listWorksheets(childId: string, page = 1) {
  return api<{
    results: WorksheetSummary[];
    next: number | null;
    count: number;
  }>(`worksheets/?child_id=${childId}&page=${page}`);
}
export function createWorksheet(childId: string, title: string) {
  return api<WorksheetSummary>("worksheets/", "POST", {
    child_id: childId,
    title,
  });
}
export function worksheetDetail(id: string) {
  return api<WorksheetDetail>(`worksheets/${id}/`);
}
export function addItem(
  worksheetId: string,
  body: { origin: "problem" | "bank" | "variant"; problem_id?: string },
) {
  return api<WorksheetItem>(`worksheets/${worksheetId}/items/`, "POST", body);
}
export function removeItem(worksheetId: string, itemId: string) {
  return api(`worksheets/${worksheetId}/items/${itemId}/`, "DELETE");
}
export function itemDetail(worksheetId: string, itemId: string) {
  return api<WorksheetItem>(`worksheets/${worksheetId}/items/${itemId}/`);
}
export function deleteWorksheet(id: string) {
  return api(`worksheets/${id}/`, "DELETE", { confirm: true });
}
export function submitAttempt(
  worksheetId: string,
  itemId: string,
  body: { answer: string; self_grade: string; duration_seconds?: number },
) {
  return api<
    AttemptRow & {
      review: { due_on: string; stage: string; interval_days: number } | null;
    }
  >(`worksheets/${worksheetId}/items/${itemId}/attempts/`, "POST", body);
}
export function reviewQueue(childId: string) {
  return api<Queue>(`reviews/queue/?child_id=${childId}`);
}
export function gradeProblem(problemId: string, grade: string) {
  return api<{
    due_on: string;
    stage: string;
    interval_days: number;
    streak: number;
  }>(`problems/${problemId}/review/`, "POST", { grade });
}
export function trends(childId: string, weeks = 8) {
  return api<Trend>(`children/${childId}/trends/?weeks=${weeks}`);
}
export function createExport(body: {
  kind: "worksheet" | "summary";
  child_id: string;
  worksheet_id?: string;
}) {
  return api<{ nonce: string; kind: string; expires_at: string; url: string }>(
    "exports/",
    "POST",
    body,
  );
}
export async function downloadExport(url: string) {
  // #ifdef H5
  const response = await fetch(url, {
    headers: { Authorization: `Bearer ${session.access}` },
  });
  if (!response.ok) throw new Error("导出链接已失效，请重新生成。");
  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = url.includes("summary") ? "learning.csv" : "worksheet.html";
  link.click();
  URL.revokeObjectURL(objectUrl);
  return;
  // #endif
  // #ifndef H5
  throw new Error("导出请使用家长端网页版；小程序内暂不支持下载文件。");
  // #endif
}
