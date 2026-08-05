export interface StoredSession {
  sessionId: string;
  title?: string;
  groupId: number;
  windowId: number;
  activeTabId?: number;
  createdAt: number;
  updatedAt: number;
}
