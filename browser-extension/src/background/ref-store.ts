import type { BrowserPageSnapshotRef } from '../shared';

export interface BrowserPageRefEntry extends BrowserPageSnapshotRef {
  text?: string;
}

function normalizeRef(ref: string): string {
  return ref.trim().replace(/^@/, '');
}

export class BrowserPageRefStore {
  private readonly refsByTabId = new Map<
    number,
    Map<string, BrowserPageRefEntry>
  >();

  reset(tabId: number, refs: BrowserPageRefEntry[]): void {
    this.refsByTabId.set(
      tabId,
      new Map(refs.map(entry => [normalizeRef(entry.ref), entry])),
    );
  }

  get(tabId: number, ref: string): BrowserPageRefEntry | undefined {
    return this.refsByTabId.get(tabId)?.get(normalizeRef(ref));
  }

  toRecord(tabId: number): Record<string, BrowserPageSnapshotRef> {
    const refs = this.refsByTabId.get(tabId);
    if (!refs) {
      return {};
    }

    return Object.fromEntries(
      Array.from(refs.entries()).map(([ref, entry]) => [
        ref,
        {
          ref,
          role: entry.role,
          ...(entry.name ? { name: entry.name } : {}),
          ...(typeof entry.nth === 'number' ? { nth: entry.nth } : {}),
          ...(typeof entry.backendNodeId === 'number'
            ? { backendNodeId: entry.backendNodeId }
            : {}),
          ...(entry.frameId ? { frameId: entry.frameId } : {}),
        },
      ]),
    );
  }
}
