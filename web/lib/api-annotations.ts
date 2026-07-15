/** 消息标注（阅读模式高亮/划线/批注）。 */

import { API_URL, headers } from "./api-base";

export type AnnotationType = "highlight" | "underline" | "strike" | "comment" | "bookmark";
export type AnnotationColor = "yellow" | "blue" | "green" | "pink" | null;

export interface Annotation {
  id: number;
  type: AnnotationType;
  color: AnnotationColor;
  start: number;
  end: number;
  quote: string | null;
  note: string | null;
  created_at: number;
}

export interface AnnotationCreatePayload {
  message_id: number;
  type: AnnotationType;
  color?: AnnotationColor;
  start: number;
  end: number;
  quote?: string | null;
  note?: string | null;
}

export async function getAnnotations(messageId: number): Promise<Annotation[]> {
  const res = await fetch(`${API_URL}/annotations/${messageId}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch annotations");
  return (await res.json()).annotations;
}

/** 一次取多个 message 的标注，返回 { "<messageId>": Annotation[] }。 */
export async function getAnnotationsBatch(messageIds: number[]): Promise<Record<string, Annotation[]>> {
  if (messageIds.length === 0) return {};
  const res = await fetch(`${API_URL}/annotations/batch?ids=${messageIds.join(",")}`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to fetch annotations");
  return res.json();
}

export async function createAnnotation(payload: AnnotationCreatePayload): Promise<number> {
  const res = await fetch(`${API_URL}/annotations`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to create annotation");
  return (await res.json()).id;
}

export async function deleteAnnotation(annoId: number): Promise<void> {
  const res = await fetch(`${API_URL}/annotations/${annoId}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to delete annotation");
}
