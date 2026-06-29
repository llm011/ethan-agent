import { BROWSER_RPC_ERROR_CODE } from '../shared';

import { BrowserExtensionRpcError } from './session-store';

const CDP_PROTOCOL_VERSION = '1.3';

function getRuntimeErrorMessage(): string | undefined {
  return chrome.runtime.lastError?.message;
}

export class CdpClient {
  private attached = false;

  private attaching: Promise<void> | null = null;

  private readonly target: chrome.debugger.Debuggee;

  constructor(readonly tabId: number) {
    this.target = { tabId };
  }

  attach(): Promise<void> {
    if (this.attached) {
      return Promise.resolve();
    }
    if (this.attaching) {
      return this.attaching;
    }

    this.attaching = new Promise((resolve, reject) => {
      chrome.debugger.attach(this.target, CDP_PROTOCOL_VERSION, () => {
        const message = getRuntimeErrorMessage();
        if (message) {
          if (message.includes('Another debugger is already attached')) {
            this.attached = true;
            this.attaching = null;
            resolve();
            return;
          }

          this.attaching = null;
          reject(createCdpError(message));
        } else {
          this.attached = true;
          this.attaching = null;
          resolve();
        }
      });
    });

    return this.attaching;
  }

  send<TResult>(
    method: string,
    commandParams?: Record<string, unknown>,
  ): Promise<TResult> {
    return new Promise((resolve, reject) => {
      chrome.debugger.sendCommand(
        this.target,
        method,
        commandParams,
        result => {
          const message = getRuntimeErrorMessage();
          if (message) {
            if (message.includes('Debugger is not attached')) {
              this.markDetached();
            }
            reject(createCdpError(message));
            return;
          }

          resolve(result as TResult);
        },
      );
    });
  }

  detach(): Promise<void> {
    if (!this.attached) {
      return Promise.resolve();
    }

    return new Promise(resolve => {
      chrome.debugger.detach(this.target, () => {
        this.markDetached();
        resolve();
      });
    });
  }

  markDetached(): void {
    this.attached = false;
    this.attaching = null;
  }
}

function createCdpError(message: string): BrowserExtensionRpcError {
  return new BrowserExtensionRpcError(
    BROWSER_RPC_ERROR_CODE.browserPageOperationFailed,
    message,
  );
}

const clientsByTabId = new Map<number, CdpClient>();
let detachListenerRegistered = false;

function ensureDetachListener(): void {
  if (detachListenerRegistered) {
    return;
  }

  chrome.debugger.onDetach.addListener(source => {
    const tabId = source.tabId;
    if (typeof tabId !== 'number') {
      return;
    }

    const client = clientsByTabId.get(tabId);
    client?.markDetached();
    clientsByTabId.delete(tabId);
  });
  detachListenerRegistered = true;
}

function getCdpClient(tabId: number): CdpClient {
  ensureDetachListener();

  let client = clientsByTabId.get(tabId);
  if (!client) {
    client = new CdpClient(tabId);
    clientsByTabId.set(tabId, client);
  }
  return client;
}

export async function releaseCdpClient(tabId: number): Promise<void> {
  const client = clientsByTabId.get(tabId);
  clientsByTabId.delete(tabId);
  await client?.detach();
}

export async function releaseAllCdpClients(): Promise<void> {
  const clients = Array.from(clientsByTabId.values());
  clientsByTabId.clear();
  await Promise.all(clients.map(client => client.detach()));
}

export async function withCdpClient<TResult>(
  tabId: number,
  run: (client: CdpClient) => Promise<TResult>,
): Promise<TResult> {
  const client = getCdpClient(tabId);
  await client.attach();
  return run(client);
}
