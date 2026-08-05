import type {
  BrowserPageSnapshotElement,
  BrowserPageViewport,
} from '../../shared';
import type { BrowserPageRefEntry } from '../ref-store';

export interface CdpPropertyValue {
  value?: unknown;
}

export interface CdpAxNode {
  nodeId: string;
  ignored?: boolean;
  role?: CdpPropertyValue;
  name?: CdpPropertyValue;
  value?: CdpPropertyValue;
  description?: CdpPropertyValue;
  childIds?: string[];
  backendDOMNodeId?: number;
  frameId?: string;
}

export interface CdpAxTreeResult {
  nodes: CdpAxNode[];
}

export interface DomDescribeNodeResult {
  node: DomNode;
}

export interface DomGetDocumentResult {
  root: {
    nodeId: number;
  };
}

export interface DomQuerySelectorResult {
  nodeId: number;
}

export interface DomNode {
  backendNodeId?: number;
  children?: DomNode[];
}

export interface RuntimeEvaluateResponse<TValue> {
  result?: {
    objectId?: string;
    value?: TValue;
  };
}

export interface CursorElementInfo {
  backendNodeId: number;
  role: string;
  name: string;
  text: string;
  kind: string;
  hints: string[];
  checked?: string;
}

export interface SnapshotNode {
  ax: CdpAxNode;
  role: string;
  name: string;
  value?: string;
  ignored: boolean;
  parentId?: string;
  children: string[];
  depth: number;
  renderDepth?: number;
  refable?: boolean;
  ref?: string;
  href?: string;
  cursor?: CursorElementInfo;
  bbox?: { x: number; y: number; w: number; h: number };
  overlay?: boolean;
  visible?: boolean;
}

export interface AxSnapshotResult {
  snapshot: string;
  elements: BrowserPageSnapshotElement[];
  refs: BrowserPageRefEntry[];
  viewport: BrowserPageViewport;
}
