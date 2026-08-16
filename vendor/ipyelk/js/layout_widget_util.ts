/**
 * Copyright (c) 2024 ipyelk contributors.
 * Distributed under the terms of the Modified BSD License.
 */

export function layoutErrorMessage(error: unknown): { action: 'error'; error: string } {
  return { action: 'error', error: `${error}` };
}
