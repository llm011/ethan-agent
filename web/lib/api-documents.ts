/**
 * 文档库 API —— Agent 产出的文档（~/.ethan/documents/）。
 *
 * 与 /docs（项目自身文档站）、/knowledge（知识库）区分：
 * 这里管理的是对话里产出的文档，支持文件树、收藏置顶、溯源到来源对话。
 */
import { API_URL, fetchWithTimeout, headers } from "./api-base";

/** 文档树节点（目录或文件）。 */
export interface DocNode {
  name: string;
  path: string;        // 相对文档库根目录的 posix 路径
  is_dir: boolean;
  mtime: number;
  // 文件专有
  size_kb?: number;
  ext?: string;
  favorite?: boolean;
  pinned?: boolean;
  session_id?: string;
  message_id?: number;
  children?: DocNode[];
}

export interface DocDetail {
  path: string;
  title: string;
  content: string;
  favorite: boolean;
  pinned: boolean;
  session_id: string;
  message_id: number;
  size_kb: number;
}

export async function fetchDocumentTree(): Promise<{ tree: DocNode[]; total: number }> {
  const res = await fetchWithTimeout(`${API_URL}/documents/tree`, { headers: headers() });
  if (!res.ok) throw new Error("Failed to load documents");
  return res.json();
}

export async function fetchDocument(path: string): Promise<DocDetail> {
  const params = new URLSearchParams({ path });
  const res = await fetchWithTimeout(`${API_URL}/documents?${params}`, { headers: headers() });
  if (!res.ok) throw new Error(`Failed to load document: ${res.status}`);
  return res.json();
}

export async function updateDocumentMeta(
  path: string,
  meta: { favorite?: boolean; pinned?: boolean; title?: string; session_id?: string; message_id?: number },
): Promise<void> {
  const params = new URLSearchParams({ path });
  const res = await fetchWithTimeout(`${API_URL}/documents?${params}`, {
    method: "PATCH",
    headers: headers(),
    body: JSON.stringify(meta),
  });
  if (!res.ok) throw new Error("Failed to update document");
}

export async function deleteDocument(path: string): Promise<void> {
  const params = new URLSearchParams({ path });
  const res = await fetchWithTimeout(`${API_URL}/documents?${params}`, {
    method: "DELETE",
    headers: headers(),
  });
  if (!res.ok) throw new Error("Failed to delete document");
}

export async function moveDocument(path: string, newPath: string): Promise<void> {
  const res = await fetchWithTimeout(`${API_URL}/documents/move`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify({ path, new_path: newPath }),
  });
  if (!res.ok) throw new Error("Failed to move document");
}

/** 文档库根目录信息（设置页/空态提示展示路径用）。 */
export async function fetchDocumentsRoot(): Promise<{ root: string; exists: boolean }> {
  const res = await fetchWithTimeout(`${API_URL}/documents/root`, { headers: headers() });
  if (!res.ok) throw new Error("Failed");
  return res.json();
}
