import type { CdpAxNode, CdpPropertyValue } from './types';
import { MAX_NAME_LENGTH } from './constants';

export function stringifyValue(value: unknown): string {
  if (value === null || typeof value === 'undefined') {
    return '';
  }
  return String(value).replace(/\s+/g, ' ').trim().slice(0, MAX_NAME_LENGTH);
}

export function literal(value: unknown): string {
  return JSON.stringify(value);
}

export function getAxValue(property: CdpPropertyValue | undefined): string {
  return stringifyValue(property?.value);
}

export function getNodeRole(node: CdpAxNode): string {
  return getAxValue(node.role) || 'generic';
}

export function getNodeName(node: CdpAxNode): string {
  return getAxValue(node.name || node.value || node.description);
}
